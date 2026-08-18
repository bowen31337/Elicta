//! Opens the vendor connection at capture start rather than at first speech
//! (architecture §14.2: "open the socket before the meeting, not at first
//! speech"), and makes that ordering observable rather than just true by
//! call-site convention.
//!
//! [`RegionPinnedBackend`](super::region::RegionPinnedBackend) already opens
//! its `inner` connection eagerly, in `open`, for a different reason
//! (binding the connection to a resolved regional endpoint for its whole
//! lifetime). [`CaptureStartBackend`] generalises the "open eagerly" half of
//! that for any backend — region-pinned or not — and adds the piece region
//! pinning doesn't need: a [`ConnectionEvent::Ready`] signal a caller can
//! observe before pushing any audio, so "connection setup happened before
//! the first utterance" is provable from event order, not just from the
//! fact that `open` was called before `start_stream`.

use std::collections::VecDeque;

use super::event::{Keyterm, StreamId, TranscriptionEvent};
use super::transcription_backend::{BackendError, TranscriptionBackend};

/// A connection-lifecycle event. Deliberately a separate type from
/// [`TranscriptionEvent`]: that enum describes what was said, this one
/// describes the connection itself, so a `Ready` signal can never be
/// mistaken for transcript content by a caller pattern-matching on
/// `TranscriptionEvent`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConnectionEvent {
    /// The vendor connection is open and able to accept `start_stream` /
    /// `send_audio` calls. Queued exactly once, the moment
    /// [`CaptureStartBackend::open`] returns — at capture start, never
    /// deferred until a stream's first utterance (architecture §14.2).
    Ready,
}

/// Wraps any [`TranscriptionBackend`] so its vendor connection is opened
/// immediately, at capture start, rather than lazily on the first
/// `start_stream` call for the first utterance.
///
/// `open` calls `connect` synchronously and queues a
/// [`ConnectionEvent::Ready`] a caller drains via
/// [`CaptureStartBackend::poll_connection_events`] before any audio is ever
/// pushed — meant to be called once per capture session, before the first
/// participant has spoken, so connection setup never lands on the first
/// nudge.
pub struct CaptureStartBackend<B: TranscriptionBackend> {
    inner: B,
    connection_events: VecDeque<ConnectionEvent>,
}

impl<B: TranscriptionBackend> CaptureStartBackend<B> {
    /// Opens `inner` immediately via `connect` and queues its `Ready`
    /// event. Nothing about `start_stream` or `send_audio` runs first —
    /// this is the "open the socket before the meeting" moment architecture
    /// §14.2 describes.
    pub fn open(connect: impl FnOnce() -> B) -> Self {
        let inner = connect();
        let mut connection_events = VecDeque::new();
        connection_events.push_back(ConnectionEvent::Ready);
        Self { inner, connection_events }
    }

    /// Drains whatever connection-lifecycle events have arrived since the
    /// last call, in arrival order. Separate from
    /// [`TranscriptionBackend::poll_events`] so a `Ready` signal is never
    /// interleaved with, or mistaken for, transcript content.
    pub fn poll_connection_events(&mut self) -> Vec<ConnectionEvent> {
        self.connection_events.drain(..).collect()
    }
}

impl<B: TranscriptionBackend> TranscriptionBackend for CaptureStartBackend<B> {
    fn start_stream(
        &mut self,
        stream_id: &StreamId,
        keyterms: &[Keyterm],
    ) -> Result<(), BackendError> {
        self.inner.start_stream(stream_id, keyterms)
    }

    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        self.inner.send_audio(stream_id, frame)
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.inner.poll_events()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::fake::ImmutablePartialFakeBackend;

    #[test]
    fn opening_connects_immediately_rather_than_waiting_for_start_stream() {
        let mut connect_called = false;

        let _backend = CaptureStartBackend::open(|| {
            connect_called = true;
            ImmutablePartialFakeBackend::new()
        });

        assert!(connect_called, "connect must run inside open, before any start_stream call");
    }

    #[test]
    fn a_ready_event_is_queued_before_any_start_stream_or_audio_is_sent() {
        let mut backend = CaptureStartBackend::open(ImmutablePartialFakeBackend::new);

        let events = backend.poll_connection_events();

        assert_eq!(events, vec![ConnectionEvent::Ready]);
    }

    #[test]
    fn the_ready_event_is_only_ever_emitted_once() {
        let mut backend = CaptureStartBackend::open(ImmutablePartialFakeBackend::new);
        assert_eq!(backend.poll_connection_events(), vec![ConnectionEvent::Ready]);

        assert!(
            backend.poll_connection_events().is_empty(),
            "a second drain should find nothing left to report"
        );
    }

    #[test]
    fn the_ready_event_precedes_the_first_utterance_end_to_end() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = CaptureStartBackend::open(ImmutablePartialFakeBackend::new);

        // Ready is observable before start_stream (and therefore before any
        // utterance) is ever called for this connection.
        let connection_events = backend.poll_connection_events();
        assert_eq!(connection_events, vec![ConnectionEvent::Ready]);

        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");
        backend.send_audio(&stream_id, &[0i16; 320]).expect("frame accepted");
        let transcription_events = backend.poll_events();

        assert!(
            !transcription_events.is_empty(),
            "the connection should still transcribe normally once opened"
        );
    }

    #[test]
    fn transcription_calls_still_delegate_through_to_the_wrapped_backend() {
        let stream_id: StreamId = "stream-1".to_string();
        let keyterms = vec!["Acme Corp".to_string()];
        let mut backend = CaptureStartBackend::open(ImmutablePartialFakeBackend::new);

        backend.start_stream(&stream_id, &keyterms).expect("handshake succeeds");
        let result = backend.send_audio(&stream_id, &[0i16; 320]);

        assert!(result.is_ok());
    }

    #[test]
    fn send_audio_before_start_stream_is_still_rejected_through_the_wrapper() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = CaptureStartBackend::open(ImmutablePartialFakeBackend::new);

        let result = backend.send_audio(&stream_id, &[0i16; 320]);

        assert!(result.is_err());
    }
}
