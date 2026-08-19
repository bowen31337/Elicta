//! macOS `ScreenCaptureKit` loopback capture backend (PRD FR-1.1) — a silent
//! local join of the system's own audio output, not an actual meeting
//! participant.
//!
//! `ScreenCaptureKit`'s stream configuration can request system audio
//! resampled and downmixed to an exact rate and channel count *by the OS*
//! (`SCStreamConfiguration::with_sample_rate` /
//! `with_channel_count` — one of `{8000, 16000, 24000, 48000}` Hz and
//! `{1, 2}` channels). This backend asks for 16kHz mono directly rather than
//! capturing at the system's native rate and resampling downstream the way
//! the Windows WASAPI loopback backend does — there's no native-format
//! mixing to preserve here, `ScreenCaptureKit` already does it once, in the
//! OS's own resampler, before the sample ever reaches this process.
//!
//! A raw CoreAudio process tap (`AudioHardwareCreateProcessTap`, macOS
//! 14.4+) is the other capture path PRD FR-1.1 names for this feature; this
//! backend uses `ScreenCaptureKit` instead because its stream configuration
//! exposes the target sample rate and channel count as first-class knobs,
//! where the process tap API hands back whatever native format the tapped
//! device runs at and leaves resampling to the caller.
//!
//! `ScreenCaptureKit` delivers audio by pushing `CMSampleBuffer`s to a
//! callback on its own dispatch queue rather than the pull-based
//! `IAudioCaptureClient::GetBuffer` polling WASAPI loopback uses, so this
//! backend bridges that push into the pull shape [`AudioSource::next_frame`]
//! needs with a channel: the callback (`AudioForwarder`) decodes and sends,
//! `next_frame` receives. Decoding the `CMSampleBuffer`'s audio buffers into
//! `RawFrame` samples is pure logic factored out to `macos_format` so that
//! part has unit test coverage on every platform, not just macOS.

#![cfg(target_os = "macos")]

use std::sync::mpsc::{sync_channel, Receiver, SyncSender};

use screencapturekit::cm::{CMSampleBuffer, CMSampleBufferExt};
use screencapturekit::error::SCError;
use screencapturekit::prelude::{
    SCContentFilter, SCShareableContent, SCStream, SCStreamConfiguration, SCStreamDelegateTrait,
    SCStreamOutputTrait, SCStreamOutputType,
};
use screencapturekit::stream::configuration::audio::{AudioChannelCount, AudioSampleRate};

use crate::ring::{AudioFormat, RawFrame};

use super::kind::AudioSourceKind;
use super::macos_format::{decode_audio_buffers, CoreAudioBuffer, CoreAudioTapFormat};
use super::source::{AudioSource, AudioSourceError};

/// The format this backend asks `ScreenCaptureKit` to deliver system audio
/// in — already this crate's normalisation target, so the downstream
/// `NormalizingPipeline` a caller runs frames through is a pass-through for
/// this source rather than a resample.
const NATIVE_SAMPLE_RATE: AudioSampleRate = AudioSampleRate::Rate16000;
const NATIVE_CHANNELS: AudioChannelCount = AudioChannelCount::Mono;

/// A minimal, unused video surface. This backend never registers a `Screen`
/// output handler, so `ScreenCaptureKit` drops every video frame immediately
/// after producing it (see `SCStream::add_output_handler` — samples with no
/// matching handler are released without ever reaching user code); a
/// non-zero size is set purely because `ScreenCaptureKit` requires one, not
/// because any pixel of it is read.
const UNUSED_VIDEO_DIMENSION: u32 = 2;

/// How many decoded audio chunks may queue between the `ScreenCaptureKit`
/// delivery queue and [`next_frame`](AudioSource::next_frame) before the
/// producer starts dropping. Chosen generously relative to
/// `ScreenCaptureKit`'s own packet cadence so a transient stall in the
/// capture consumer doesn't drop audio under normal operation, while still
/// bounding memory if the consumer stops entirely.
const FRAME_QUEUE_CAPACITY: usize = 64;

/// One item flowing from the `ScreenCaptureKit` delivery queue to
/// [`next_frame`](AudioSource::next_frame): either a decoded audio chunk, or
/// the terminal error the stream stopped with.
enum StreamEvent {
    Samples(Vec<f32>),
    StoppedWithError(String),
}

/// A running `ScreenCaptureKit` audio-only capture session against the
/// system's audio output.
pub struct ScreenCaptureLoopbackSource {
    /// Kept alive for the life of this source purely so `ScreenCaptureKit`
    /// keeps delivering to `events_rx` — never read directly after `open`.
    stream: SCStream,
    events_rx: Receiver<StreamEvent>,
    format: AudioFormat,
}

/// Decodes each delivered audio sample buffer and forwards it to
/// [`ScreenCaptureLoopbackSource::next_frame`] over a channel.
///
/// Must never block: `ScreenCaptureKit` invokes this on its own delivery
/// queue, and blocking it would stall every subsequent packet. `try_send`
/// drops a chunk outright if `next_frame` has fallen far enough behind to
/// fill [`FRAME_QUEUE_CAPACITY`], rather than backing up audio delivery to
/// wait for it.
struct AudioForwarder {
    tx: SyncSender<StreamEvent>,
}

impl SCStreamOutputTrait for AudioForwarder {
    fn did_output_sample_buffer(&self, sample: CMSampleBuffer, of_type: SCStreamOutputType) {
        if of_type != SCStreamOutputType::Audio {
            return;
        }
        let Some(buffer_list) = sample.audio_buffer_list() else {
            return;
        };
        let buffers: Vec<CoreAudioBuffer<'_>> = buffer_list
            .iter()
            .map(|buffer| CoreAudioBuffer {
                channels: buffer.number_channels as u16,
                data: buffer.data(),
            })
            .collect();
        let samples = decode_audio_buffers(&buffers);
        let _ = self.tx.try_send(StreamEvent::Samples(samples));
    }
}

/// Forwards `ScreenCaptureKit`'s one stop notification (an unexpected stop —
/// permission revoked, the tapped display disconnected, the system tearing
/// the stream down) into the same event channel `next_frame` reads.
struct StopForwarder {
    tx: SyncSender<StreamEvent>,
}

impl SCStreamDelegateTrait for StopForwarder {
    fn did_stop_with_error(&self, error: SCError) {
        let _ = self
            .tx
            .try_send(StreamEvent::StoppedWithError(error.to_string()));
    }
}

impl ScreenCaptureLoopbackSource {
    /// Starts a silent local capture of the system's audio output. Fails if
    /// `ScreenCaptureKit` has no shareable content available (no display, or
    /// screen-recording permission not yet granted — `ScreenCaptureKit`
    /// gates audio-only capture behind the same permission as video) or the
    /// stream refuses to start.
    pub fn open() -> Result<Self, AudioSourceError> {
        let content = SCShareableContent::get().map_err(|e| {
            AudioSourceError::Disconnected(format!("failed to enumerate shareable content: {e}"))
        })?;
        let display = content.displays().into_iter().next().ok_or_else(|| {
            AudioSourceError::Disconnected(
                "no display available for a silent local join".to_string(),
            )
        })?;

        let filter = SCContentFilter::create()
            .with_display(&display)
            .with_excluding_windows(&[])
            .build();

        let config = SCStreamConfiguration::new()
            .with_captures_audio(true)
            .with_sample_rate(NATIVE_SAMPLE_RATE)
            .with_channel_count(NATIVE_CHANNELS)
            .with_excludes_current_process_audio(true)
            .with_width(UNUSED_VIDEO_DIMENSION)
            .with_height(UNUSED_VIDEO_DIMENSION);

        let (tx, rx) = sync_channel(FRAME_QUEUE_CAPACITY);

        let mut stream =
            SCStream::new_with_delegate(&filter, &config, StopForwarder { tx: tx.clone() });
        stream.add_output_handler(AudioForwarder { tx }, SCStreamOutputType::Audio);

        stream.start_capture().map_err(|e| {
            AudioSourceError::Disconnected(format!(
                "failed to start ScreenCaptureKit audio capture: {e}"
            ))
        })?;

        let format = CoreAudioTapFormat {
            sample_rate: NATIVE_SAMPLE_RATE.as_hz() as u32,
            channels: NATIVE_CHANNELS.as_count() as u16,
        }
        .audio_format();

        Ok(Self {
            stream,
            events_rx: rx,
            format,
        })
    }
}

impl AudioSource for ScreenCaptureLoopbackSource {
    fn kind(&self) -> AudioSourceKind {
        AudioSourceKind::Loopback
    }

    fn format(&self) -> AudioFormat {
        self.format
    }

    fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError> {
        match self.events_rx.recv() {
            Ok(StreamEvent::Samples(samples)) => Ok(Some(RawFrame::new(self.format, samples))),
            Ok(StreamEvent::StoppedWithError(reason)) => {
                Err(AudioSourceError::Disconnected(reason))
            }
            Err(_) => Err(AudioSourceError::Disconnected(
                "ScreenCaptureKit audio stream ended unexpectedly".to_string(),
            )),
        }
    }
}

impl Drop for ScreenCaptureLoopbackSource {
    fn drop(&mut self) {
        let _ = self.stream.stop_capture();
    }
}

/// Fails the build on this platform if the backend stops being movable to the
/// audio thread — a regression that would otherwise only surface as a compile
/// error in whatever spawns the capture thread, far from its cause.
const _: () = {
    const fn assert_send<T: Send>() {}
    assert_send::<ScreenCaptureLoopbackSource>();
};
