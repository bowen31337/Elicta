use std::collections::HashMap;

use super::event::TokenEvent;
use super::socket::{validate_backend, BackendRejected, TokenSocket, TokenSocketFactory};
use super::ParticipantId;

/// Owns exactly one [`TokenSocket`] per participant seen so far, and routes
/// each participant's separated audio to its own socket instead of ever
/// sharing one connection across participants (PRD FR-2.10).
///
/// The invariant this type exists to hold: `active_stream_count()` always
/// equals the number of distinct participants dispatched to, never more
/// (two participants can't collapse onto one socket) and never less (one
/// participant can't fan out across several).
pub struct ParticipantTokenStreams<F: TokenSocketFactory> {
    factory: F,
    sockets: HashMap<ParticipantId, F::Socket>,
}

impl<F: TokenSocketFactory> ParticipantTokenStreams<F> {
    /// Validates `factory` against this crate's per-token-confidence
    /// requirement (PRD FR-2.3, NFR-5.6) before constructing anything, and
    /// fails startup with a [`BackendRejected`] error rather than accepting
    /// a vendor that can only ever report one confidence score for a whole
    /// utterance — such a vendor would leave every dispatched `TokenEvent`
    /// backed by a score the input-span gate can't trust per span.
    pub fn new(factory: F) -> Result<Self, BackendRejected> {
        validate_backend(&factory)?;
        Ok(Self {
            factory,
            sockets: HashMap::new(),
        })
    }

    /// Number of participants currently emitting their own event stream.
    pub fn active_stream_count(&self) -> usize {
        self.sockets.len()
    }

    pub fn is_active(&self, participant_id: &str) -> bool {
        self.sockets.contains_key(participant_id)
    }

    /// Routes one frame of separated audio for `participant_id` to that
    /// participant's dedicated socket — opening a new one the first time
    /// this participant is seen, and reusing it on every later call — and
    /// returns whatever token events that socket alone produced.
    pub fn dispatch(&mut self, participant_id: &ParticipantId, samples: &[i16]) -> Vec<TokenEvent> {
        let factory = &mut self.factory;
        let socket = self
            .sockets
            .entry(participant_id.clone())
            .or_insert_with(|| factory.open(participant_id));
        socket.send_audio(samples)
    }

    /// Ends and removes a participant's socket, e.g. once the managed
    /// capture vendor reports that participant has left the meeting. A
    /// later `dispatch` for the same id opens a fresh socket rather than
    /// resurrecting the closed one.
    pub fn end(&mut self, participant_id: &str) {
        if let Some(mut socket) = self.sockets.remove(participant_id) {
            socket.close();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::super::socket::ConfidenceGranularity;
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    #[derive(Default)]
    struct OpenLog(Rc<RefCell<Vec<ParticipantId>>>);

    struct MockSocket {
        participant_id: ParticipantId,
        closed: Rc<RefCell<Vec<ParticipantId>>>,
    }

    impl TokenSocket for MockSocket {
        fn send_audio(&mut self, samples: &[i16]) -> Vec<TokenEvent> {
            // Echo the frame length back as the "transcript" so a test can
            // tell which socket handled which call without any shared
            // state between sockets.
            vec![TokenEvent::partial(
                self.participant_id.clone(),
                format!("{}samples", samples.len()),
                0.9,
            )]
        }

        fn close(&mut self) {
            self.closed.borrow_mut().push(self.participant_id.clone());
        }
    }

    struct MockFactory {
        opened: Rc<RefCell<Vec<ParticipantId>>>,
        closed: Rc<RefCell<Vec<ParticipantId>>>,
    }

    impl MockFactory {
        fn new() -> (Self, OpenLog, Rc<RefCell<Vec<ParticipantId>>>) {
            let opened = Rc::new(RefCell::new(Vec::new()));
            let closed = Rc::new(RefCell::new(Vec::new()));
            (
                MockFactory {
                    opened: opened.clone(),
                    closed: closed.clone(),
                },
                OpenLog(opened),
                closed,
            )
        }
    }

    impl TokenSocketFactory for MockFactory {
        type Socket = MockSocket;

        fn open(&mut self, participant_id: &ParticipantId) -> Self::Socket {
            self.opened.borrow_mut().push(participant_id.clone());
            MockSocket {
                participant_id: participant_id.clone(),
                closed: self.closed.clone(),
            }
        }

        fn confidence_granularity(&self) -> ConfidenceGranularity {
            ConfidenceGranularity::PerToken
        }
    }

    /// A vendor stand-in that only ever reports one confidence score per
    /// whole utterance — the shape [`validate_backend`] must reject before
    /// this crate ever opens a socket against it.
    struct UtteranceLevelOnlyFactory;

    impl TokenSocketFactory for UtteranceLevelOnlyFactory {
        type Socket = MockSocket;

        fn open(&mut self, participant_id: &ParticipantId) -> Self::Socket {
            MockSocket {
                participant_id: participant_id.clone(),
                closed: Rc::new(RefCell::new(Vec::new())),
            }
        }

        fn confidence_granularity(&self) -> ConfidenceGranularity {
            ConfidenceGranularity::UtteranceLevel
        }
    }

    #[test]
    fn a_backend_reporting_only_utterance_level_confidence_is_rejected_at_startup() {
        let result = ParticipantTokenStreams::new(UtteranceLevelOnlyFactory);

        let err = match result {
            Err(err) => err,
            Ok(_) => panic!(
                "a backend that can't supply per-token confidence must fail startup, not succeed"
            ),
        };
        assert!(
            err.0.contains("utterance-level") && err.0.contains("per-token"),
            "rejection message must clearly explain why: {}",
            err.0
        );
    }

    #[test]
    fn a_backend_reporting_per_token_confidence_is_accepted_at_startup() {
        let (factory, _opened, _closed) = MockFactory::new();

        assert!(ParticipantTokenStreams::new(factory).is_ok());
    }

    #[test]
    fn each_participant_gets_its_own_socket() {
        let (factory, opened, _closed) = MockFactory::new();
        let mut streams =
            ParticipantTokenStreams::new(factory).expect("factory reports per-token confidence");

        streams.dispatch(&"alice".to_string(), &[0; 10]);
        streams.dispatch(&"bob".to_string(), &[0; 20]);

        assert_eq!(streams.active_stream_count(), 2);
        assert!(streams.is_active("alice"));
        assert!(streams.is_active("bob"));
        assert_eq!(
            opened.0.borrow().as_slice(),
            &["alice".to_string(), "bob".to_string()]
        );
    }

    #[test]
    fn repeated_dispatch_for_same_participant_reuses_one_socket() {
        let (factory, opened, _closed) = MockFactory::new();
        let mut streams =
            ParticipantTokenStreams::new(factory).expect("factory reports per-token confidence");

        for _ in 0..5 {
            streams.dispatch(&"alice".to_string(), &[0; 4]);
        }

        assert_eq!(streams.active_stream_count(), 1);
        assert_eq!(
            opened.0.borrow().len(),
            1,
            "socket must be opened once, not per frame"
        );
    }

    #[test]
    fn each_participant_emits_its_own_independent_event_stream() {
        let (factory, _opened, _closed) = MockFactory::new();
        let mut streams =
            ParticipantTokenStreams::new(factory).expect("factory reports per-token confidence");

        let alice_events = streams.dispatch(&"alice".to_string(), &[0; 3]);
        let bob_events = streams.dispatch(&"bob".to_string(), &[0; 7]);

        // Each participant's returned events are tagged with that
        // participant alone and reflect only the audio dispatched to that
        // participant's socket — never a mix of the two.
        assert_eq!(alice_events.len(), 1);
        assert_eq!(alice_events[0].participant_id, "alice");
        assert_eq!(bob_events.len(), 1);
        assert_eq!(bob_events[0].participant_id, "bob");
        assert_ne!(alice_events[0].text, bob_events[0].text);
    }

    #[test]
    fn every_dispatched_token_carries_a_confidence_value() {
        let (factory, _opened, _closed) = MockFactory::new();
        let mut streams =
            ParticipantTokenStreams::new(factory).expect("factory reports per-token confidence");

        let events = streams.dispatch(&"alice".to_string(), &[0; 3]);

        assert!(!events.is_empty());
        for event in &events {
            assert!(
                event.confidence > 0.0,
                "every token dispatched through the registry must carry a populated confidence"
            );
        }
    }

    #[test]
    fn ending_a_participant_closes_its_socket_and_frees_the_slot() {
        let (factory, opened, closed) = MockFactory::new();
        let mut streams =
            ParticipantTokenStreams::new(factory).expect("factory reports per-token confidence");

        streams.dispatch(&"alice".to_string(), &[0; 1]);
        streams.end("alice");

        assert!(!streams.is_active("alice"));
        assert_eq!(closed.borrow().as_slice(), &["alice".to_string()]);

        // Dispatching again after end opens a brand new socket rather than
        // reusing the closed one.
        streams.dispatch(&"alice".to_string(), &[0; 1]);
        assert_eq!(
            opened.0.borrow().as_slice(),
            &["alice".to_string(), "alice".to_string()]
        );
    }
}
