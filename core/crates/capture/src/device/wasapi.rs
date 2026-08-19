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

/// A running WASAPI loopback capture session against the current default
/// render endpoint.
pub struct WasapiLoopbackSource {
    capture_client: IAudioCaptureClient,
    audio_client: IAudioClient,
    format: WasapiMixFormat,
    /// Whether this instance is the one that called `CoInitializeEx` on this
    /// thread (`S_OK`) rather than finding COM already initialized
    /// (`S_FALSE`) — only the caller that initialized COM should
    /// uninitialize it on drop.
    owns_com_init: bool,
}

impl WasapiLoopbackSource {
    /// Opens the default render endpoint in loopback mode and starts
    /// capture. Fails if no render endpoint exists (no speakers/output
    /// device configured) or the endpoint refuses shared-mode loopback
    /// initialization.
    ///
    /// Must be called on the thread that will subsequently call
    /// [`next_frame`](AudioSource::next_frame) — COM apartment state is
    /// per-thread, and the capture worker this crate's normalisation
    /// pipeline runs on (`core::ring`) is exactly that thread.
    pub fn open() -> Result<Self, AudioSourceError> {
        unsafe {
            let init_hr = CoInitializeEx(None, COINIT_MULTITHREADED);
            if init_hr.is_err() {
                return Err(AudioSourceError::Disconnected(format!(
                    "CoInitializeEx failed: {init_hr:?}"
                )));
            }
            // S_OK means this call initialized COM on this thread; S_FALSE
            // means it was already initialized by someone else, who owns
            // tearing it down.
            let owns_com_init = init_hr.0 == 0;

            match Self::open_with_com_initialized(owns_com_init) {
                Ok(source) => Ok(source),
                Err(err) => {
                    if owns_com_init {
                        CoUninitialize();
                    }
                    Err(err)
                }
            }
        }
    }

    unsafe fn open_with_com_initialized(owns_com_init: bool) -> Result<Self, AudioSourceError> {
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
            owns_com_init,
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
        unsafe {
            let _ = self.audio_client.Stop();
            if self.owns_com_init {
                CoUninitialize();
            }
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

/// Fails the build on this platform if the backend stops being movable to the
/// audio thread — a regression that would otherwise only surface as a compile
/// error in whatever spawns the capture thread, far from its cause.
const _: () = {
    const fn assert_send<T: Send>() {}
    assert_send::<WasapiLoopbackSource>();
};
