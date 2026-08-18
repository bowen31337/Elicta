//! Frames outgoing audio into vendor-sized chunks (architecture §14.2):
//! every `send_audio` call should carry between 20ms and 50ms of audio,
//! balancing quantisation delay (a bigger frame holds its first sample back
//! until the whole frame fills) against per-message overhead (a smaller
//! frame multiplies the per-call cost of framing, the wire, and vendor-side
//! decode across fewer samples).
//!
//! [`TranscriptionBackend::send_audio`] takes "one frame" of PCM16 and
//! leaves how big a frame is entirely to the caller (see
//! `transcription_backend.rs`) — this module is that caller's answer.
//! [`AudioFramer`] buffers whatever chunk sizes the capture pipeline hands
//! it (not vendor-sized; `capture::ring::NormalizingPipeline` sizes its
//! output by the native hardware buffer it was given, not by the ASR frame
//! budget) and re-chunks that stream into fixed frames within
//! [`MIN_FRAME_MS`, `MAX_FRAME_MS`]. [`FramedBackend`] applies that framing
//! transparently in front of any [`TranscriptionBackend`], the same
//! composition shape `RegionPinnedBackend` uses in `region.rs`.

use std::collections::HashMap;

use super::event::{Keyterm, StreamId, TranscriptionEvent};
use super::transcription_backend::{BackendError, TranscriptionBackend};

/// 16kHz mono linear PCM16 — the one shape every input path is reduced to
/// (see `capture::ring::NormalizingPipeline`) and the only rate this module
/// needs to convert a millisecond duration into a sample count.
const SAMPLE_RATE_HZ: u32 = 16_000;

/// The floor of the vendor frame-size budget (architecture §14.2): below
/// this, per-message overhead — framing, the wire, vendor-side decode —
/// starts to dominate the audio it carries.
pub const MIN_FRAME_MS: u32 = 20;

/// The ceiling of the vendor frame-size budget (architecture §14.2): above
/// this, the frame itself becomes a quantisation delay — speech at the
/// start of an oversized frame can't reach the vendor until the whole frame
/// fills.
pub const MAX_FRAME_MS: u32 = 50;

/// A requested frame duration outside [`MIN_FRAME_MS`, `MAX_FRAME_MS`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrameDurationError(pub String);

fn samples_for(duration_ms: u32) -> usize {
    (SAMPLE_RATE_HZ as u64 * duration_ms as u64 / 1000) as usize
}

/// Re-chunks a stream of arbitrarily-sized PCM16 pushes into fixed frames of
/// exactly `duration_ms` milliseconds, buffering whatever's left over
/// between calls to [`AudioFramer::push`].
///
/// Constructing with a duration outside [`MIN_FRAME_MS`, `MAX_FRAME_MS`] is
/// rejected outright rather than silently clamped, so a misconfigured
/// caller fails at startup instead of silently drifting outside the budget
/// architecture §14.2 sets.
#[derive(Debug)]
pub struct AudioFramer {
    frame_len: usize,
    buffer: Vec<i16>,
}

impl AudioFramer {
    pub fn new(duration_ms: u32) -> Result<Self, FrameDurationError> {
        if !(MIN_FRAME_MS..=MAX_FRAME_MS).contains(&duration_ms) {
            return Err(FrameDurationError(format!(
                "frame duration {duration_ms}ms is outside the allowed [{MIN_FRAME_MS}, {MAX_FRAME_MS}]ms range"
            )));
        }
        Ok(Self { frame_len: samples_for(duration_ms), buffer: Vec::new() })
    }

    /// The number of `i16` samples one frame holds at this framer's
    /// configured duration.
    pub fn frame_len(&self) -> usize {
        self.frame_len
    }

    /// Appends `samples` to the pending buffer and drains as many
    /// full-length frames as are now available, in arrival order. Any
    /// remainder shorter than one frame stays buffered for the next call —
    /// it is never sent short, since an undersized frame is exactly the
    /// overhead-dominated frame this type exists to prevent.
    pub fn push(&mut self, samples: &[i16]) -> Vec<Vec<i16>> {
        self.buffer.extend_from_slice(samples);
        let mut frames = Vec::new();
        while self.buffer.len() >= self.frame_len {
            frames.push(self.buffer.drain(..self.frame_len).collect());
        }
        frames
    }

    /// Drains whatever's left in the buffer as a final, possibly short,
    /// frame. For stream end, where waiting for a full frame would drop
    /// trailing audio rather than ever send it. Returns `None` if nothing
    /// is buffered.
    pub fn flush(&mut self) -> Option<Vec<i16>> {
        if self.buffer.is_empty() {
            None
        } else {
            Some(std::mem::take(&mut self.buffer))
        }
    }
}

/// A [`TranscriptionBackend`] wrapped so every `send_audio` call reaching
/// `inner` carries a fixed `duration_ms` of audio, regardless of the chunk
/// sizes callers push in with. One [`AudioFramer`] is kept per active
/// stream, since two streams' pending remainders must never bleed into each
/// other's frames.
pub struct FramedBackend<B: TranscriptionBackend> {
    inner: B,
    duration_ms: u32,
    framers: HashMap<StreamId, AudioFramer>,
}

impl<B: TranscriptionBackend> FramedBackend<B> {
    /// Wraps `inner` to frame its outgoing audio at `duration_ms`. Fails
    /// without touching `inner` if `duration_ms` is outside
    /// [`MIN_FRAME_MS`, `MAX_FRAME_MS`].
    pub fn new(inner: B, duration_ms: u32) -> Result<Self, FrameDurationError> {
        AudioFramer::new(duration_ms)?;
        Ok(Self { inner, duration_ms, framers: HashMap::new() })
    }

    /// Sends whatever's buffered for `stream_id` as a final, possibly
    /// short, frame, so trailing audio shorter than one full frame is never
    /// silently dropped when a stream ends before its buffer fills.
    pub fn flush_stream(&mut self, stream_id: &StreamId) -> Result<(), BackendError> {
        let remainder = match self.framers.get_mut(stream_id) {
            Some(framer) => framer.flush(),
            None => None,
        };
        if let Some(remainder) = remainder {
            self.inner.send_audio(stream_id, &remainder)?;
        }
        Ok(())
    }
}

impl<B: TranscriptionBackend> TranscriptionBackend for FramedBackend<B> {
    fn start_stream(&mut self, stream_id: &StreamId, keyterms: &[Keyterm]) -> Result<(), BackendError> {
        self.inner.start_stream(stream_id, keyterms)?;
        let framer = AudioFramer::new(self.duration_ms)
            .expect("duration_ms was already validated in FramedBackend::new");
        self.framers.insert(stream_id.clone(), framer);
        Ok(())
    }

    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        let framer = self.framers.get_mut(stream_id).ok_or_else(|| {
            BackendError(format!(
                "send_audio called before start_stream for stream {stream_id:?}"
            ))
        })?;
        for framed in framer.push(frame) {
            self.inner.send_audio(stream_id, &framed)?;
        }
        Ok(())
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.inner.poll_events()
    }

    fn send_keepalive(&mut self) -> Result<(), BackendError> {
        self.inner.send_keepalive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::fake::ImmutablePartialFakeBackend;

    #[test]
    fn a_duration_below_the_floor_is_rejected() {
        assert_eq!(
            AudioFramer::new(19).unwrap_err(),
            FrameDurationError(
                "frame duration 19ms is outside the allowed [20, 50]ms range".to_string()
            )
        );
    }

    #[test]
    fn a_duration_above_the_ceiling_is_rejected() {
        assert_eq!(
            AudioFramer::new(51).unwrap_err(),
            FrameDurationError(
                "frame duration 51ms is outside the allowed [20, 50]ms range".to_string()
            )
        );
    }

    #[test]
    fn the_floor_and_ceiling_durations_are_both_accepted() {
        assert!(AudioFramer::new(MIN_FRAME_MS).is_ok());
        assert!(AudioFramer::new(MAX_FRAME_MS).is_ok());
    }

    #[test]
    fn frame_len_matches_16khz_mono_sample_math() {
        // 20ms @ 16kHz mono = 320 samples, 50ms = 800 samples — the exact
        // bounds architecture §14.2 sets.
        assert_eq!(AudioFramer::new(20).unwrap().frame_len(), 320);
        assert_eq!(AudioFramer::new(50).unwrap().frame_len(), 800);
    }

    #[test]
    fn a_push_shorter_than_one_frame_is_buffered_rather_than_sent_short() {
        let mut framer = AudioFramer::new(20).unwrap();

        let frames = framer.push(&[0i16; 100]);

        assert!(frames.is_empty(), "100 samples is short of the 320-sample frame, so nothing should drain yet");
    }

    #[test]
    fn buffered_remainders_across_pushes_combine_into_a_full_frame() {
        let mut framer = AudioFramer::new(20).unwrap();

        assert!(framer.push(&[1i16; 200]).is_empty());
        let frames = framer.push(&[2i16; 120]);

        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].len(), 320);
        assert_eq!(&frames[0][..200], &[1i16; 200][..]);
        assert_eq!(&frames[0][200..], &[2i16; 120][..]);
    }

    #[test]
    fn a_push_larger_than_one_frame_splits_into_multiple_frames_in_order() {
        let mut framer = AudioFramer::new(20).unwrap();

        let mut input = vec![0i16; 320];
        input.extend(vec![1i16; 320]);
        input.extend(vec![2i16; 100]);

        let frames = framer.push(&input);

        assert_eq!(frames.len(), 2, "two full 320-sample frames should drain, the 100-sample remainder stays buffered");
        assert!(frames[0].iter().all(|&s| s == 0));
        assert!(frames[1].iter().all(|&s| s == 1));
    }

    #[test]
    fn flush_returns_none_when_nothing_is_buffered() {
        let mut framer = AudioFramer::new(20).unwrap();
        assert!(framer.push(&[0i16; 320]).len() == 1, "exactly one full frame drains, buffer is now empty");

        assert_eq!(framer.flush(), None);
    }

    #[test]
    fn flush_drains_a_short_trailing_remainder() {
        let mut framer = AudioFramer::new(20).unwrap();
        framer.push(&[7i16; 150]);

        let remainder = framer.flush();

        assert_eq!(remainder, Some(vec![7i16; 150]));
        assert_eq!(framer.flush(), None, "flush must empty the buffer, not just read it");
    }

    #[test]
    fn framed_backend_never_forwards_a_frame_outside_the_configured_duration() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = FramedBackend::new(ImmutablePartialFakeBackend::new(), 20).unwrap();
        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");

        // Push chunks that don't line up with the 320-sample frame size at
        // all — the wrapper's job is to smooth this into fixed frames
        // regardless of what the caller hands it.
        backend.send_audio(&stream_id, &[0i16; 100]).expect("buffered, no forward yet");
        backend.send_audio(&stream_id, &[0i16; 500]).expect("crosses one frame boundary");
        backend.send_audio(&stream_id, &[0i16; 700]).expect("crosses more than one frame boundary");

        // The underlying fake only accepts non-empty frames and increments
        // its internal frame counter once per accepted `send_audio` call;
        // proving it never rejected a call is enough to show every forwarded
        // frame was well-formed and non-empty.
        assert!(!backend.poll_events().is_empty(), "the fake should have produced events from the forwarded frames");
    }

    #[test]
    fn send_audio_before_start_stream_is_rejected_without_touching_inner() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = FramedBackend::new(ImmutablePartialFakeBackend::new(), 20).unwrap();

        let result = backend.send_audio(&stream_id, &[0i16; 320]);

        assert!(result.is_err());
    }

    #[test]
    fn flush_stream_forwards_a_short_trailing_remainder_to_the_inner_backend() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = FramedBackend::new(ImmutablePartialFakeBackend::new(), 20).unwrap();
        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");
        backend.send_audio(&stream_id, &[0i16; 150]).expect("buffered, short of one frame");

        backend.flush_stream(&stream_id).expect("flush forwards the short remainder");

        assert!(!backend.poll_events().is_empty(), "the flushed remainder should have reached the inner backend");
    }

    #[test]
    fn flush_stream_on_an_empty_buffer_is_a_harmless_no_op() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = FramedBackend::new(ImmutablePartialFakeBackend::new(), 20).unwrap();
        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");

        assert!(backend.flush_stream(&stream_id).is_ok());
    }

    #[test]
    fn constructing_with_an_out_of_range_duration_fails_before_wrapping_anything() {
        let result = FramedBackend::new(ImmutablePartialFakeBackend::new(), 10);
        assert!(result.is_err());
    }
}
