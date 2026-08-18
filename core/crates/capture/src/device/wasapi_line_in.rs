//! Windows WASAPI line-in capture backend (PRD FR-1.1) — a first-class
//! [`AudioSource`] for a physical line-in interface (a USB audio interface
//! plugged in as the input device), not the render endpoint's own output.
//!
//! Line-in capture means opening the *default capture* endpoint's
//! `IAudioClient` in plain shared mode — no `AUDCLNT_STREAMFLAGS_LOOPBACK` —
//! so WASAPI hands back whatever the interface's own input is receiving,
//! rather than looping back the system's render mix the way
//! `WasapiLoopbackSource` does. Everything below the endpoint activation
//! (mix format parsing, packet polling, buffer decoding) is identical in
//! shape to the loopback backend and shares its byte-decoding logic with it
//! via `wasapi_format`, which has no dependency on which endpoint direction
//! produced the bytes.

#![cfg(target_os = "windows")]

use std::ptr;
use std::time::Duration;

use windows::Win32::Media::Audio::{
    eCapture, eConsole, IAudioCaptureClient, IAudioClient, IMMDevice, IMMDeviceEnumerator,
    MMDeviceEnumerator, AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_SHAREMODE_SHARED,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_ALL,
    COINIT_MULTITHREADED,
};

use crate::ring::{AudioFormat, RawFrame};

use super::kind::AudioSourceKind;
use super::source::{AudioSource, AudioSourceError};
use super::wasapi::parse_wave_format;
use super::wasapi_format::{decode_capture_packet, WasapiMixFormat};

/// Buffer duration requested from WASAPI for the line-in capture client, in
/// 100-nanosecond units (the unit `IAudioClient::Initialize` takes) — 200ms
/// gives the non-real-time capture worker headroom to drain packets between
/// polls without the endpoint's shared-mode buffer overrunning.
const BUFFER_DURATION_100NS: i64 = 200 * 10_000;

/// How long to sleep between `GetNextPacketSize` polls when the endpoint has
/// nothing new yet — short enough not to add perceptible latency ahead of a
/// shared-mode device period, long enough not to spin the capture thread.
const POLL_INTERVAL: Duration = Duration::from_millis(5);

/// A running WASAPI capture session against the current default capture
/// endpoint (a physical line-in interface).
pub struct WasapiLineInSource {
    capture_client: IAudioCaptureClient,
    audio_client: IAudioClient,
    format: WasapiMixFormat,
    /// Whether this instance is the one that called `CoInitializeEx` on this
    /// thread (`S_OK`) rather than finding COM already initialized
    /// (`S_FALSE`) — only the caller that initialized COM should
    /// uninitialize it on drop.
    owns_com_init: bool,
}

impl WasapiLineInSource {
    /// Opens the default capture endpoint and starts capture. Fails if no
    /// capture endpoint exists (no line-in interface configured as the input
    /// device) or the endpoint refuses shared-mode initialization.
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
            .GetDefaultAudioEndpoint(eCapture, eConsole)
            .map_err(|e| {
                AudioSourceError::Disconnected(format!("no default capture endpoint: {e}"))
            })?;

        let audio_client: IAudioClient = device
            .Activate(CLSCTX_ALL, None)
            .map_err(|e| AudioSourceError::Disconnected(format!("failed to activate audio client: {e}")))?;

        let mix_format_ptr = audio_client
            .GetMixFormat()
            .map_err(|e| AudioSourceError::Disconnected(format!("GetMixFormat failed: {e}")))?;
        let format = parse_wave_format(mix_format_ptr);

        let init_result = audio_client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            0,
            BUFFER_DURATION_100NS,
            0,
            mix_format_ptr,
            None,
        );
        CoTaskMemFree(Some(mix_format_ptr as *const core::ffi::c_void));
        init_result.map_err(|e| {
            AudioSourceError::Disconnected(format!("failed to initialize line-in capture: {e}"))
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

impl AudioSource for WasapiLineInSource {
    fn kind(&self) -> AudioSourceKind {
        AudioSourceKind::LineIn
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

impl Drop for WasapiLineInSource {
    fn drop(&mut self) {
        unsafe {
            let _ = self.audio_client.Stop();
            if self.owns_com_init {
                CoUninitialize();
            }
        }
    }
}
