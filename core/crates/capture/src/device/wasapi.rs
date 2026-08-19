//! Windows WASAPI loopback capture backend (PRD FR-1.1) — a first-class
//! [`AudioSource`] for the default render endpoint's own output, not a
//! workaround bolted onto the input side of the API.
//!
//! Loopback capture means opening the *default render* endpoint's
//! `IAudioClient` with `AUDCLNT_STREAMFLAGS_LOOPBACK` instead of opening a
//! capture endpoint — WASAPI hands back exactly what that endpoint is
//! playing, mixed, at its own shared-mode format. This module owns the COM
//! lifecycle that setup needs; decoding the packets it yields into
//! [`RawFrame`] samples is pure logic factored out to `wasapi_format` so
//! that part has unit test coverage on every platform, not just Windows.

#![cfg(target_os = "windows")]

use std::ptr;
use std::time::Duration;

use windows::core::GUID;
use windows::Win32::Media::Audio::{
    eConsole, eRender, IAudioCaptureClient, IAudioClient, IMMDevice, IMMDeviceEnumerator,
    MMDeviceEnumerator, AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_SHAREMODE_SHARED,
    AUDCLNT_STREAMFLAGS_LOOPBACK, WAVEFORMATEX, WAVEFORMATEXTENSIBLE,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_ALL,
    COINIT_MULTITHREADED,
};

use crate::ring::{AudioFormat, RawFrame};

use super::kind::AudioSourceKind;
use super::source::{AudioSource, AudioSourceError};
use super::wasapi_format::{decode_capture_packet, WasapiMixFormat, WasapiSampleFormat};

/// Buffer duration requested from WASAPI for the loopback capture client, in
/// 100-nanosecond units (the unit `IAudioClient::Initialize` takes) — 200ms
/// gives the non-real-time capture worker headroom to drain packets between
/// polls without the endpoint's shared-mode buffer overrunning.
const BUFFER_DURATION_100NS: i64 = 200 * 10_000;

/// How long to sleep between `GetNextPacketSize` polls when the endpoint has
/// nothing new yet — short enough not to add perceptible latency ahead of a
/// shared-mode device period, long enough not to spin the capture thread.
const POLL_INTERVAL: Duration = Duration::from_millis(5);

const WAVE_FORMAT_PCM: u16 = 1;
const WAVE_FORMAT_IEEE_FLOAT: u16 = 3;
const WAVE_FORMAT_EXTENSIBLE: u16 = 0xFFFE;

// `windows` only generates these GUID constants behind the
// `Win32_Media_KernelStreaming` / `Win32_Media_Multimedia` features; pulling
// either in for two well-known, never-changing subtype GUIDs isn't worth the
// extra feature surface.
const KSDATAFORMAT_SUBTYPE_PCM: GUID = GUID::from_u128(0x00000001_0000_0010_8000_00aa00389b71);
const KSDATAFORMAT_SUBTYPE_IEEE_FLOAT: GUID =
    GUID::from_u128(0x00000003_0000_0010_8000_00aa00389b71);

/// Ties multi-threaded-apartment membership to the *thread* rather than to a
/// capture source.
///
/// COM apartment state is per-thread, and `CoUninitialize` only balances a
/// `CoInitializeEx` made on that same thread. A source cannot own that: it is
/// opened on whichever thread asked for a device and then moved to the
/// dedicated audio thread that pulls from it — `AudioSource` requires `Send`
/// precisely so it can be. An apartment owned by the object would therefore be
/// left from the wrong thread and leaked on the right one.
///
/// A thread-local owns it instead. Its `Drop` runs at thread exit, on the
/// thread that entered, which is the only place the call balances.
struct ComApartment {
    /// `S_OK` means this call put the thread in the apartment and must take it
    /// back out; `S_FALSE` means it was already a member and whoever put it
    /// there owns the exit.
    entered_here: bool,
}

impl ComApartment {
    fn enter() -> Result<Self, String> {
        // SAFETY: callable on any thread; the HRESULT distinguishes "entered"
        // from "was already a member".
        let hr = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
        if hr.is_err() {
            return Err(format!("CoInitializeEx failed: {hr:?}"));
        }
        Ok(Self { entered_here: hr.0 == 0 })
    }
}

impl Drop for ComApartment {
    fn drop(&mut self) {
        if self.entered_here {
            // SAFETY: balances this thread's own successful `CoInitializeEx`,
            // and runs at thread exit on that same thread.
            unsafe { CoUninitialize() };
        }
    }
}

thread_local! {
    /// A failure is cached rather than retried: a thread that cannot enter the
    /// apartment will not start being able to between packets, and retrying
    /// per call would turn one error into one per frame.
    static APARTMENT: Result<ComApartment, String> = ComApartment::enter();
}

/// Puts the calling thread in the multi-threaded apartment if it is not there
/// already, and keeps it there for the rest of the thread's life.
///
/// Every entry point that touches a COM interface calls this — opening a
/// device, pulling a frame, stopping one on drop — because any of them can be
/// the first thing a given thread does.
///
/// `pub(super)` so the line-in backend shares one apartment policy with this
/// one rather than keeping a second copy of it.
pub(super) fn enter_apartment() -> Result<(), AudioSourceError> {
    APARTMENT
        .try_with(|apartment| match apartment {
            Ok(_) => Ok(()),
            Err(reason) => Err(AudioSourceError::Disconnected(reason.clone())),
        })
        // `try_with` fails only once the thread-local has been destroyed, i.e.
        // during thread teardown, when nothing can be captured anyway.
        .unwrap_or_else(|_| {
            Err(AudioSourceError::Disconnected(
                "COM apartment already torn down on this thread".to_string(),
            ))
        })
}

/// A running WASAPI loopback capture session against the current default
/// render endpoint.
pub struct WasapiLoopbackSource {
    capture_client: IAudioCaptureClient,
    audio_client: IAudioClient,
    format: WasapiMixFormat,
}

impl WasapiLoopbackSource {
    /// Opens the default render endpoint in loopback mode and starts
    /// capture. Fails if no render endpoint exists (no speakers/output
    /// device configured) or the endpoint refuses shared-mode loopback
    /// initialization.
    ///
    /// Callable from any thread. The apartment this needs is entered per
    /// thread by [`enter_apartment`], so the source it returns may then be
    /// moved to the audio thread that pulls from it — which is what the
    /// caller actually does.
    pub fn open() -> Result<Self, AudioSourceError> {
        enter_apartment()?;
        // SAFETY: this thread is now a member of the multi-threaded apartment.
        unsafe { Self::open_in_apartment() }
    }

    unsafe fn open_in_apartment() -> Result<Self, AudioSourceError> {
        let enumerator: IMMDeviceEnumerator = CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
            .map_err(|e| {
                AudioSourceError::Disconnected(format!("failed to create device enumerator: {e}"))
            })?;

        let device: IMMDevice = enumerator
            .GetDefaultAudioEndpoint(eRender, eConsole)
            .map_err(|e| AudioSourceError::Disconnected(format!("no default render endpoint: {e}")))?;

        let audio_client: IAudioClient = device
            .Activate(CLSCTX_ALL, None)
            .map_err(|e| AudioSourceError::Disconnected(format!("failed to activate audio client: {e}")))?;

        let mix_format_ptr = audio_client
            .GetMixFormat()
            .map_err(|e| AudioSourceError::Disconnected(format!("GetMixFormat failed: {e}")))?;
        let format = parse_wave_format(mix_format_ptr);

        let init_result = audio_client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK,
            BUFFER_DURATION_100NS,
            0,
            mix_format_ptr,
            None,
        );
        CoTaskMemFree(Some(mix_format_ptr as *const core::ffi::c_void));
        init_result.map_err(|e| {
            AudioSourceError::Disconnected(format!("failed to initialize loopback capture: {e}"))
        })?;
        let format =
            format.map_err(|reason| AudioSourceError::Disconnected(format!("unusable mix format: {reason}")))?;

        let capture_client: IAudioCaptureClient = audio_client
            .GetService()
            .map_err(|e| AudioSourceError::Disconnected(format!("GetService failed: {e}")))?;

        audio_client
            .Start()
            .map_err(|e| AudioSourceError::Disconnected(format!("failed to start capture: {e}")))?;

        Ok(Self {
            capture_client,
            audio_client,
            format,
        })
    }
}

impl AudioSource for WasapiLoopbackSource {
    fn kind(&self) -> AudioSourceKind {
        AudioSourceKind::Loopback
    }

    fn format(&self) -> AudioFormat {
        self.format.audio_format()
    }

    fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError> {
        // This is normally the audio thread rather than the one that opened
        // the device, and it has to be in the apartment before the first
        // interface call rather than after it.
        enter_apartment()?;
        loop {
            let packet_frames = unsafe { self.capture_client.GetNextPacketSize() }
                .map_err(|e| AudioSourceError::Disconnected(format!("GetNextPacketSize failed: {e}")))?;

            if packet_frames == 0 {
                std::thread::sleep(POLL_INTERVAL);
                continue;
            }

            let mut data_ptr: *mut u8 = ptr::null_mut();
            let mut frames_available = 0u32;
            let mut flags = 0u32;
            unsafe {
                self.capture_client
                    .GetBuffer(&mut data_ptr, &mut frames_available, &mut flags, None, None)
                    .map_err(|e| AudioSourceError::Disconnected(format!("GetBuffer failed: {e}")))?;
            }

            let is_silent = flags & AUDCLNT_BUFFERFLAGS_SILENT.0 as u32 != 0;
            let byte_len = frames_available as usize
                * self.format.channels as usize
                * self.format.bytes_per_sample();
            let samples = unsafe {
                let bytes = std::slice::from_raw_parts(data_ptr, byte_len);
                decode_capture_packet(bytes, frames_available, self.format, is_silent)
            };

            unsafe {
                self.capture_client
                    .ReleaseBuffer(frames_available)
                    .map_err(|e| AudioSourceError::Disconnected(format!("ReleaseBuffer failed: {e}")))?;
            }

            return Ok(Some(RawFrame::new(self.format.audio_format(), samples)));
        }
    }
}

impl Drop for WasapiLoopbackSource {
    fn drop(&mut self) {
        // A source can be dropped on a thread that never pulled from it, so
        // the apartment may still need entering. If it cannot be, `Stop` is
        // skipped: leaking a stopped-anyway stream at process exit is better
        // than calling a COM method from outside any apartment.
        if enter_apartment().is_err() {
            return;
        }
        // SAFETY: this thread is in the apartment these pointers belong to.
        unsafe {
            let _ = self.audio_client.Stop();
        }
    }
}

/// Reads the `WAVEFORMATEX` WASAPI allocated for `GetMixFormat`, following
/// into its `WAVEFORMATEXTENSIBLE` tail when the format tag says the caller
/// must. `ptr` must point at a live `WAVEFORMATEX` (or larger
/// `WAVEFORMATEXTENSIBLE`) as returned by `IAudioClient::GetMixFormat` — the
/// caller frees it with `CoTaskMemFree` once this has copied out the fields
/// it needs.
///
/// `pub(super)` rather than private: `wasapi_line_in`'s capture endpoint
/// hands back the exact same `WAVEFORMATEX`/`WAVEFORMATEXTENSIBLE` shape from
/// its own `GetMixFormat` call, so it reuses this parser instead of
/// duplicating it.
pub(super) unsafe fn parse_wave_format(ptr: *mut WAVEFORMATEX) -> Result<WasapiMixFormat, String> {
    // WAVEFORMATEX/WAVEFORMATEXTENSIBLE are `packed(1)` to match WASAPI's C
    // layout exactly, so every field is copied to a local before use —
    // taking `&wfx.field` directly would build a reference the field's own
    // type may require stricter alignment than the packed struct guarantees.
    let wfx = *ptr;
    let channels = wfx.nChannels;
    let sample_rate = wfx.nSamplesPerSec;
    let format_tag = wfx.wFormatTag;
    let bits_per_sample = wfx.wBitsPerSample;

    let sample_format = match format_tag {
        WAVE_FORMAT_IEEE_FLOAT => WasapiSampleFormat::Float32,
        WAVE_FORMAT_PCM if bits_per_sample == 16 => WasapiSampleFormat::Pcm16,
        WAVE_FORMAT_EXTENSIBLE => {
            let ext = *(ptr as *const WAVEFORMATEXTENSIBLE);
            let sub_format = ext.SubFormat;
            if sub_format == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT {
                WasapiSampleFormat::Float32
            } else if sub_format == KSDATAFORMAT_SUBTYPE_PCM && bits_per_sample == 16 {
                WasapiSampleFormat::Pcm16
            } else {
                return Err(format!(
                    "unsupported extensible sub-format (bits/sample={bits_per_sample})"
                ));
            }
        }
        tag => return Err(format!("unsupported mix format tag {tag:#x}")),
    };

    Ok(WasapiMixFormat {
        sample_rate,
        channels,
        sample_format,
    })
}

// SAFETY: the fields are COM interface pointers, which the `windows` crate
// leaves `!Send` because an interface pointer *in general* may be bound to the
// apartment that created it. These are not. Every thread that touches one is a
// member of the multi-threaded apartment — `enter_apartment` is called when
// opening a device, on every frame and on drop — and within a single apartment
// interface pointers pass freely, without marshalling. The MTA is one
// apartment shared by every thread that joins it, so moving this to the audio
// thread hands it back to the apartment it was created in rather than across a
// boundary.
//
// What makes that true is that the apartment is *not* owned here; see
// `ComApartment` for why owning it would break exactly this property.
unsafe impl Send for WasapiLoopbackSource {}

/// Fails the build on this platform if the backend stops being movable to the
/// audio thread — a regression that would otherwise only surface as a compile
/// error in whatever spawns the capture thread, far from its cause.
const _: () = {
    const fn assert_send<T: Send>() {}
    assert_send::<WasapiLoopbackSource>();
};
