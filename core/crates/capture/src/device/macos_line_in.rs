//! macOS CoreAudio line-in capture backend (PRD FR-1.1) — a first-class
//! [`AudioSource`] for a physical line-in interface (a USB audio interface
//! plugged in as the input device), the macOS counterpart to
//! `WasapiLineInSource` on Windows.
//!
//! Line-in capture means opening an AUHAL (`kAudioUnitSubType_HALOutput`)
//! audio unit against the current default *input* device, rather than the
//! `ScreenCaptureKit` session `ScreenCaptureLoopbackSource` opens against the
//! system's own output — CoreAudio hands back whatever the interface's own
//! input is receiving, at that device's native sample rate and channel
//! count, not a resampled system-audio mix. This backend requests that same
//! native sample rate and channel count back from the AUHAL rather than
//! asking it to resample, and leaves normalising to this crate's 16kHz mono
//! target to `core::ring`'s `NormalizingPipeline` downstream — exactly the
//! division of responsibility `WasapiLineInSource` uses for its own native
//! WASAPI mix format.
//!
//! Built on the `coreaudio-rs` crate's `AudioUnit` wrapper rather than raw
//! `AudioComponent`/`AudioUnitRender` FFI: `AudioUnit::set_input_callback`
//! already does the "allocate an `AudioBufferList`, pull the next block with
//! `AudioUnitRender`, hand back typed samples" dance CoreAudio's AUHAL input
//! path otherwise requires by hand — the same class of glue the
//! `screencapturekit` crate spares `macos.rs` for the loopback path. Because
//! that wrapper hands back already-decoded `&[f32]` interleaved samples
//! instead of raw `AudioBufferList` bytes, there is no byte-decoding step
//! here worth factoring out to a `_format` module the way
//! `macos_format`/`wasapi_format` do for the other two backends.
//!
//! CoreAudio's input callback runs on its own real-time IO thread, so, like
//! `ScreenCaptureLoopbackSource`, this backend bridges that push into the
//! pull shape [`AudioSource::next_frame`] needs with a bounded channel: the
//! callback forwards decoded sample chunks, `next_frame` receives them.

#![cfg(target_os = "macos")]

use std::sync::mpsc::{sync_channel, Receiver, RecvTimeoutError};
use std::time::Duration;

/// How long a running device may deliver nothing before it is called broken.
///
/// Generous rather than tight: the first buffer can take a moment after the
/// unit starts, and calling a working microphone dead mid-meeting would be
/// worse than the silence it is meant to explain.
const SILENT_DEVICE_TIMEOUT: Duration = Duration::from_secs(5);

use coreaudio::audio_unit::audio_format::LinearPcmFlags;
use coreaudio::audio_unit::macos_helpers::{
    audio_unit_from_device_id, get_audio_device_ids_for_scope, get_default_device_id,
    get_device_name, get_device_transport_type,
};
use coreaudio::audio_unit::render_callback::{self, data};
use coreaudio::audio_unit::{AudioUnit, Element, SampleFormat, Scope, StreamFormat};

use crate::ring::{AudioFormat, RawFrame};

use super::input::{is_built_in_transport, select, InputDevice};
use super::kind::AudioSourceKind;
use super::source::{AudioSource, AudioSourceError};

/// How many decoded sample chunks may queue between the CoreAudio input
/// callback (running on CoreAudio's own real-time IO thread) and
/// [`next_frame`](AudioSource::next_frame) before the producer starts
/// dropping. Sized the same as `ScreenCaptureLoopbackSource`'s queue for the
/// same reason: generous relative to the native callback cadence so a
/// transient stall in the capture consumer doesn't drop audio under normal
/// operation, while still bounding memory if the consumer stops entirely.
const FRAME_QUEUE_CAPACITY: usize = 64;

/// A running AUHAL capture session against the current default input device
/// (a physical line-in interface).
pub struct CoreAudioLineInSource {
    /// Kept alive for the life of this source purely so CoreAudio keeps
    /// invoking the input callback that feeds `events_rx` — never read
    /// directly after `open`.
    audio_unit: AudioUnit,
    events_rx: Receiver<Vec<f32>>,
    format: AudioFormat,
}

/// Every input CoreAudio can see, in the order it reports them.
///
/// Devices that report no input scope are skipped rather than listed and
/// refused later: an output-only interface in an input picker is a row that
/// exists only to fail. A device whose name cannot be read is skipped for the
/// same reason — there is nothing to put in the list, and an entry called
/// "unknown" is a row nobody can choose deliberately.
pub fn input_devices() -> Vec<InputDevice> {
    let default = get_default_device_id(true);
    let Ok(ids) = get_audio_device_ids_for_scope(Scope::Input) else {
        // The whole list, not one device, failed. Reported as empty rather
        // than as an error: the picker's own "nothing is connected" is a
        // truthful description of what the operator can choose from, and the
        // system-default path stays open regardless.
        return Vec::new();
    };

    ids.into_iter()
        .filter_map(|id| {
            let name = get_device_name(id).ok()?;
            Some(InputDevice {
                id: id.to_string(),
                name,
                is_default: Some(id) == default,
                // Unreadable transport means "not known to be built in".
                // The wrong way round would put the FR-1.2 warning on an
                // interface that does not deserve it, and a warning that
                // fires on the good path is one nobody reads on the bad one.
                is_built_in: get_device_transport_type(id)
                    .map(is_built_in_transport)
                    .unwrap_or(false),
            })
        })
        .collect()
}

impl CoreAudioLineInSource {
    /// Opens the current default input device and starts capture.
    ///
    /// Equivalent to [`open_device`](Self::open_device) with no device asked
    /// for. Kept because most callers genuinely have no preference, and
    /// spelling that as `open_device(None)` at every call site reads like an
    /// omission rather than a choice.
    pub fn open() -> Result<Self, AudioSourceError> {
        Self::open_device(None)
    }

    /// Opens one input device by id and starts capture.
    ///
    /// `None` opens whatever the OS prefers, which is all this backend could
    /// ever do before. Fails if the requested device is no longer connected,
    /// if no input device exists at all, or if the AUHAL audio unit refuses
    /// configuration or initialization.
    pub fn open_device(requested: Option<&str>) -> Result<Self, AudioSourceError> {
        let available = input_devices();
        let device_id = match select(&available, requested)? {
            // Chosen deliberately: parsed back from the string this backend
            // itself produced, so a failure here means the id was invented
            // somewhere above rather than that the device went away.
            // Type left to inference rather than named: `AudioDeviceID` is
            // defined in a crate this one does not depend on directly, and the
            // default arm below already pins it to whatever coreaudio-rs says.
            Some(device) => device.id.parse().map_err(|_| {
                AudioSourceError::Disconnected(format!(
                    "'{}' is not an input this build can address",
                    device.id
                ))
            })?,
            None => get_default_device_id(true).ok_or_else(|| {
                AudioSourceError::Disconnected(
                    "no default input device (no line-in interface configured as the input device)"
                        .to_string(),
                )
            })?,
        };

        let mut audio_unit = audio_unit_from_device_id(device_id, true).map_err(|e| {
            AudioSourceError::Disconnected(format!("failed to open input audio unit: {e}"))
        })?;

        // Before this backend overrides it below, the AUHAL's input-element
        // client format (`Scope::Output`, `Element::Input`) mirrors the
        // device's own current sample rate and channel count — reading it
        // here is this backend's equivalent of WASAPI's `GetMixFormat`.
        let native = audio_unit.input_stream_format().map_err(|e| {
            AudioSourceError::Disconnected(format!(
                "failed to read native input stream format: {e}"
            ))
        })?;

        // Request that same sample rate and channel count back, but as plain
        // interleaved 32-bit float — CoreAudio's canonical PCM format, and
        // the one shape `render_callback::data::Interleaved<f32>` below
        // decodes without this backend deinterleaving planar buffers by
        // hand. No sample-rate conversion is requested here; `core::ring`'s
        // `NormalizingPipeline` resamples to this crate's 16kHz mono target
        // downstream, same as `WasapiLineInSource`.
        let desired = StreamFormat {
            sample_rate: native.sample_rate,
            sample_format: SampleFormat::F32,
            flags: LinearPcmFlags::IS_FLOAT | LinearPcmFlags::IS_PACKED,
            channels: native.channels,
        };
        audio_unit
            .set_stream_format(desired, Scope::Output, Element::Input)
            .map_err(|e| {
                AudioSourceError::Disconnected(format!("failed to set input stream format: {e}"))
            })?;

        let format = AudioFormat::new(native.sample_rate.round() as u32, native.channels as u16);

        let (tx, rx) = sync_channel::<Vec<f32>>(FRAME_QUEUE_CAPACITY);

        type CallbackArgs = render_callback::Args<data::Interleaved<f32>>;
        audio_unit
            .set_input_callback(move |args: CallbackArgs| {
                let render_callback::Args { data, .. } = args;
                let _ = tx.try_send(data.buffer.to_vec());
                Ok(())
            })
            .map_err(|e| {
                AudioSourceError::Disconnected(format!("failed to set input callback: {e}"))
            })?;

        audio_unit
            .start()
            .map_err(|e| AudioSourceError::Disconnected(format!("failed to start capture: {e}")))?;

        Ok(Self {
            audio_unit,
            events_rx: rx,
            format,
        })
    }
}

impl AudioSource for CoreAudioLineInSource {
    fn kind(&self) -> AudioSourceKind {
        AudioSourceKind::LineIn
    }

    fn format(&self) -> AudioFormat {
        self.format
    }

    fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError> {
        // Waited for with a limit, not indefinitely. A device that is open and
        // delivering nothing is the failure this backend actually meets —
        // permission never granted, or granted to a differently-signed build
        // of the same app — and an unbounded `recv` turns it into a thread
        // parked for the length of the meeting: no frames, no error, and a
        // screen that can only report that no level has arrived.
        //
        // Silence is not this. CoreAudio delivers buffers continuously while
        // a device is running, and a quiet room arrives as buffers of zeros,
        // so several seconds with no buffer at all means the device is not
        // running rather than that nobody is speaking.
        match self.events_rx.recv_timeout(SILENT_DEVICE_TIMEOUT) {
            Ok(samples) => Ok(Some(RawFrame::new(self.format, samples))),
            Err(RecvTimeoutError::Timeout) => Err(AudioSourceError::Disconnected(format!(
                "the microphone delivered no audio for {} seconds. macOS may not have \
                 granted this build access to it — check System Settings, Privacy & \
                 Security, Microphone",
                SILENT_DEVICE_TIMEOUT.as_secs()
            ))),
            Err(RecvTimeoutError::Disconnected) => Err(AudioSourceError::Disconnected(
                "CoreAudio input callback stopped delivering audio".to_string(),
            )),
        }
    }
}

impl Drop for CoreAudioLineInSource {
    fn drop(&mut self) {
        let _ = self.audio_unit.stop();
    }
}

/// Fails the build on this platform if the backend stops being movable to the
/// audio thread — a regression that would otherwise only surface as a compile
/// error in whatever spawns the capture thread, far from its cause.
const _: () = {
    const fn assert_send<T: Send>() {}
    assert_send::<CoreAudioLineInSource>();
};
