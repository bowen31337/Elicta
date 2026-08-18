//! Holds the vendor connection open for the duration of the meeting via
//! fixed-interval keepalive frames (architecture §14.2: "held with
//! keepalives rather than reopened per utterance" — the deferred half of the
//! eager-open story `connection.rs` and `region.rs` already cover; see
//! `HANDOFF.md`'s "deliberately out of scope" note, which is exactly this).
//!
//! Real audio traffic already keeps a websocket alive on its own; the gap
//! this module closes is silence — whenever no `send_audio` (or
//! `start_stream`) call has reached the wrapped backend for a full
//! `interval`, [`KeepaliveBackend`] calls
//! [`TranscriptionBackend::send_keepalive`] and resets its clock, so a quiet
//! stretch of the meeting never lets the connection sit idle long enough to
//! time out.
//!
//! Deliberately driven by an explicit [`KeepaliveBackend::tick`] call rather
//! than a background timer or async task: this crate is std-only and
//! non-networked (see `HANDOFF.md`), and every other backend wrapper here
//! (`FramedBackend`, `CaptureStartBackend`, `RegionPinnedBackend`) is
//! synchronous push/drain for the same reason. Whatever drives real wall
//! time — a timer thread, an event loop tick — lives outside this crate;
//! this type only needs to be told how much time has passed.

use std::time::Duration;

use super::event::{Keyterm, StreamId, TranscriptionEvent};
use super::transcription_backend::{BackendError, TranscriptionBackend};

/// The fixed interval architecture §14.2 holds the connection open on.
/// Chosen well under vendor idle-timeout windows (Deepgram and AssemblyAI
/// both tolerate silence well past this before dropping a streaming
/// connection), so ticking at this cadence never lets the connection get
/// close to the actual timeout before a keepalive lands.
pub const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(5);

/// Wraps any [`TranscriptionBackend`] so its vendor connection is held open
/// with a keepalive frame every fixed `interval` of silence, rather than
/// being left to whatever idle-timeout the vendor enforces.
///
/// The idle clock is per-connection, not per-stream — architecture §14.2's
/// connection is opened once per engagement, and a keepalive has no
/// `stream_id` to address (see [`TranscriptionBackend::send_keepalive`]).
/// Any `start_stream` or `send_audio` call resets the clock, since real
/// traffic on the connection already serves the same purpose a keepalive
/// would.
pub struct KeepaliveBackend<B: TranscriptionBackend> {
    inner: B,
    interval: Duration,
    since_last_activity: Duration,
    keepalives_sent: u64,
}

impl<B: TranscriptionBackend> KeepaliveBackend<B> {
    /// Wraps `inner` so it receives a keepalive every `interval` of
    /// silence, timed from the moment this wrapper is constructed.
    pub fn new(inner: B, interval: Duration) -> Self {
        Self { inner, interval, since_last_activity: Duration::ZERO, keepalives_sent: 0 }
    }

    /// Wraps `inner` using [`KEEPALIVE_INTERVAL`], the fixed cadence
    /// architecture §14.2 calls for.
    pub fn with_default_interval(inner: B) -> Self {
        Self::new(inner, KEEPALIVE_INTERVAL)
    }

    /// Advances the idle clock by `elapsed`, sending exactly one keepalive
    /// through the wrapped backend for every full `interval` that has
    /// passed without activity resetting it — an `elapsed` spanning three
    /// intervals in one call sends three keepalives, so a caller that ticks
    /// coarsely (or catches up after a pause) never under-counts.
    ///
    /// Stops and reports the first [`BackendError`] a keepalive send
    /// returns; whatever time was already folded into the clock before that
    /// failure stays folded in, so a caller that retries `tick` with `0`
    /// elapsed picks the schedule back up rather than losing the accrued
    /// interval.
    pub fn tick(&mut self, elapsed: Duration) -> Result<(), BackendError> {
        self.since_last_activity += elapsed;
        while self.since_last_activity >= self.interval {
            self.inner.send_keepalive()?;
            self.keepalives_sent += 1;
            self.since_last_activity -= self.interval;
        }
        Ok(())
    }

    /// How many keepalive frames this wrapper has sent since construction —
    /// lets a caller (or a test) observe the fixed-interval cadence
    /// directly rather than only inferring it from the wrapped backend.
    pub fn keepalives_sent(&self) -> u64 {
        self.keepalives_sent
    }
}

impl<B: TranscriptionBackend> TranscriptionBackend for KeepaliveBackend<B> {
    fn start_stream(
        &mut self,
        stream_id: &StreamId,
        keyterms: &[Keyterm],
    ) -> Result<(), BackendError> {
        self.inner.start_stream(stream_id, keyterms)?;
        self.since_last_activity = Duration::ZERO;
        Ok(())
    }

    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        self.inner.send_audio(stream_id, frame)?;
        self.since_last_activity = Duration::ZERO;
        Ok(())
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.inner.poll_events()
    }

    fn send_keepalive(&mut self) -> Result<(), BackendError> {
        self.inner.send_keepalive()?;
        self.since_last_activity = Duration::ZERO;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::fake::ImmutablePartialFakeBackend;

    fn backend_with_interval(secs: u64) -> KeepaliveBackend<ImmutablePartialFakeBackend> {
        KeepaliveBackend::new(ImmutablePartialFakeBackend::new(), Duration::from_secs(secs))
    }

    #[test]
    fn no_keepalive_is_sent_before_a_full_interval_has_elapsed() {
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(4)).expect("tick succeeds");

        assert_eq!(backend.keepalives_sent(), 0);
    }

    #[test]
    fn a_keepalive_is_sent_the_moment_the_interval_is_reached() {
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(5)).expect("tick succeeds");

        assert_eq!(backend.keepalives_sent(), 1);
    }

    #[test]
    fn ticking_across_several_intervals_at_once_sends_one_keepalive_per_interval() {
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(17)).expect("tick succeeds");

        assert_eq!(backend.keepalives_sent(), 3, "17s / 5s = 3 full intervals");
    }

    #[test]
    fn repeated_small_ticks_accumulate_toward_the_next_interval() {
        let mut backend = backend_with_interval(5);

        for _ in 0..4 {
            backend.tick(Duration::from_secs(1)).expect("tick succeeds");
        }
        assert_eq!(backend.keepalives_sent(), 0, "4s accrued is still short of the 5s interval");

        backend.tick(Duration::from_secs(1)).expect("tick succeeds");
        assert_eq!(backend.keepalives_sent(), 1, "the 5th second completes the interval");
    }

    #[test]
    fn every_keepalive_tick_reaches_the_wrapped_backend() {
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(10)).expect("tick succeeds");

        assert_eq!(backend.keepalives_sent(), 2);
    }

    #[test]
    fn sending_audio_resets_the_idle_clock_so_a_keepalive_is_not_sent_early() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = backend_with_interval(5);
        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");

        backend.tick(Duration::from_secs(4)).expect("tick succeeds");
        backend.send_audio(&stream_id, &[0i16; 320]).expect("frame accepted");
        backend.tick(Duration::from_secs(4)).expect("tick succeeds");

        assert_eq!(
            backend.keepalives_sent(),
            0,
            "audio at the 4s mark should reset the clock, so the second 4s tick shouldn't reach 5s"
        );
    }

    #[test]
    fn starting_a_stream_resets_the_idle_clock() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(4)).expect("tick succeeds");
        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");
        backend.tick(Duration::from_secs(4)).expect("tick succeeds");

        assert_eq!(backend.keepalives_sent(), 0, "start_stream at the 4s mark should reset the clock");
    }

    #[test]
    fn a_keepalive_resets_the_clock_so_the_next_one_waits_a_full_interval() {
        let mut backend = backend_with_interval(5);

        backend.tick(Duration::from_secs(5)).expect("first interval sends one keepalive");
        assert_eq!(backend.keepalives_sent(), 1);

        backend.tick(Duration::from_secs(4)).expect("tick succeeds");
        assert_eq!(backend.keepalives_sent(), 1, "only 4s have passed since the last keepalive");

        backend.tick(Duration::from_secs(1)).expect("tick succeeds");
        assert_eq!(backend.keepalives_sent(), 2, "the second full interval completes here");
    }

    #[test]
    fn transcription_calls_still_delegate_through_to_the_wrapped_backend() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = backend_with_interval(5);

        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");
        backend.send_audio(&stream_id, &[0i16; 320]).expect("frame accepted");

        assert!(!backend.poll_events().is_empty(), "the fake should still produce transcription events");
    }

    #[test]
    fn send_audio_before_start_stream_is_still_rejected_through_the_wrapper() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = backend_with_interval(5);

        let result = backend.send_audio(&stream_id, &[0i16; 320]);

        assert!(result.is_err());
    }

    #[test]
    fn with_default_interval_uses_the_documented_keepalive_interval() {
        let mut backend = KeepaliveBackend::with_default_interval(ImmutablePartialFakeBackend::new());

        backend.tick(KEEPALIVE_INTERVAL - Duration::from_millis(1)).expect("tick succeeds");
        assert_eq!(backend.keepalives_sent(), 0);

        backend.tick(Duration::from_millis(1)).expect("tick succeeds");
        assert_eq!(backend.keepalives_sent(), 1);
    }
}
