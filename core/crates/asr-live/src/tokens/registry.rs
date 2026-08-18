use std::collections::HashMap;

use super::event::TokenEvent;
use super::socket::{validate_backend, BackendRejected, TokenSocket, TokenSocketFactory};
use super::utterance_table::{FinalizedUtterance, UtteranceTable};
use super::ParticipantId;

/// Owns exactly one [`TokenSocket`] per participant seen so far, and routes
/// each participant's separated audio to its own socket instead of ever
/// sharing one connection across participants (PRD FR-2.10).
///
/// The invariant this type exists to hold: `active_stream_count()` always
/// equals the number of distinct participants dispatched to, never more
/// (two participants can't collapse onto one socket) and never less (one
/// participant can't fan out across several).
///
/// Also owns the [`UtteranceTable`] every finalized token is appended to:
/// `dispatch` persists a finalized event to `table` before it ever appears
/// in the `Vec<TokenEvent>` handed back to its caller, so there is no way to
/// read a finalized event out of this type before it is already durably
/// recorded.
pub struct ParticipantTokenStreams<F: TokenSocketFactory, T: UtteranceTable> {
    factory: F,
    table: T,
    sockets: HashMap<ParticipantId, F::Socket>,
}

impl<F: TokenSocketFactory, T: UtteranceTable> ParticipantTokenStreams<F, T> {
    /// Validates `factory` against this crate's per-token-confidence
    /// requirement (PRD FR-2.3, NFR-5.6) before constructing anything, and
    /// fails startup with a [`BackendRejected`] error rather than accepting
    /// a vendor that can only ever report one confidence score for a whole
    /// utterance — such a vendor would leave every dispatched `TokenEvent`
    /// backed by a score the input-span gate can't trust per span.
    pub fn new(factory: F, table: T) -> Result<Self, BackendRejected> {
        validate_backend(&factory)?;
        Ok(Self {
            factory,
            table,
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

    /// The append-only utterances table every finalized event dispatched
    /// through this type has already been recorded to by the time it's
    /// visible here.
    pub fn table(&self) -> &T {
        &self.table
    }

    /// Routes one frame of separated audio for `participant_id` to that
    /// participant's dedicated socket — opening a new one the first time
    /// this participant is seen, and reusing it on every later call —
    /// persists every finalized event that socket produced to the
    /// utterances table, and only then returns the full set of events (both
    /// partial and finalized) to the caller.
    pub fn dispatch(&mut self, participant_id: &ParticipantId, samples: &[i16]) -> Vec<TokenEvent> {
        let factory = &mut self.factory;
        let socket = self
            .sockets
            .entry(participant_id.clone())
            .or_insert_with(|| factory.open(participant_id));
        let events = socket.send_audio(samples);

        for event in &events {
            if event.is_final {
                let utterance = FinalizedUtterance::from_token(event.clone())
                    .expect("event.is_final was just checked above");
                self.table.append(utterance);
            }
        }

        events
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
    use super::super::utterance_table::InMemoryUtteranceTable;
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    #[derive(Default)]
    struct OpenLog(Rc<RefCell<Vec<ParticipantId>>>);

    struct MockSocket {
        participant_id: ParticipantId,
        closed: Rc<RefCell<Vec<ParticipantId>>>,
        finalize: bool,
    }

    impl TokenSocket for MockSocket {
        fn send_audio(&mut self, samples: &[i16]) -> Vec<TokenEvent> {
            // Echo the frame length back as the "transcript" so a test can
            // tell which socket handled which call without any shared
            // state between sockets.
            let text = format!("{}samples", samples.len());
            vec![if self.finalize {
                TokenEvent::finalized(self.participant_id.clone(), text, 0.9)
            } else {
                TokenEvent::partial(self.participant_id.clone(), text, 0.9)
            }]
        }

        fn close(&mut self) {
            self.closed.borrow_mut().push(self.participant_id.clone());
        }
    }

    /// A socket whose single `send_audio` call returns several events at
    /// once, mixing partial and final tokens in a fixed order — the shape a
    /// real vendor frame can actually take (e.g. a trailing partial revised
    /// into a final within the same drain), which `MockSocket` above never
    /// exercises since it always returns exactly one event per call.
    struct MixedSocket {
        participant_id: ParticipantId,
    }

    impl TokenSocket for MixedSocket {
        fn send_audio(&mut self, _samples: &[i16]) -> Vec<TokenEvent> {
            vec![
                TokenEvent::partial(self.participant_id.clone(), "we", 0.5),
                TokenEvent::finalized(self.participant_id.clone(), "we need", 0.95),
                TokenEvent::partial(self.participant_id.clone(), "to", 0.4),
                TokenEvent::finalized(self.participant_id.clone(), "to ship", 0.92),
            ]
        }

        fn close(&mut self) {}
    }

    struct MixedFactory;

    impl TokenSocketFactory for MixedFactory {
        type Socket = MixedSocket;

        fn open(&mut self, participant_id: &ParticipantId) -> Self::Socket {
            MixedSocket {
                participant_id: participant_id.clone(),
            }
        }

        fn confidence_granularity(&self) -> ConfidenceGranularity {
            ConfidenceGranularity::PerToken
        }
    }

    struct MockFactory {
        opened: Rc<RefCell<Vec<ParticipantId>>>,
        closed: Rc<RefCell<Vec<ParticipantId>>>,
        finalize: bool,
    }

    impl MockFactory {
        fn new() -> (Self, OpenLog, Rc<RefCell<Vec<ParticipantId>>>) {
            let opened = Rc::new(RefCell::new(Vec::new()));
            let closed = Rc::new(RefCell::new(Vec::new()));
            (
                MockFactory {
                    opened: opened.clone(),
                    closed: closed.clone(),
                    finalize: false,
                },
                OpenLog(opened),
                closed,
            )
        }

        /// A variant whose sockets emit finalized tokens rather than
        /// partials, for exercising the utterances-table persistence path.
        fn new_finalizing() -> Self {
            let (mut factory, _opened, _closed) = Self::new();
            factory.finalize = true;
            factory
        }
    }

    impl TokenSocketFactory for MockFactory {
        type Socket = MockSocket;

        fn open(&mut self, participant_id: &ParticipantId) -> Self::Socket {
            self.opened.borrow_mut().push(participant_id.clone());
            MockSocket {
                participant_id: participant_id.clone(),
                closed: self.closed.clone(),
                finalize: self.finalize,
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
                finalize: false,
            }
        }

        fn confidence_granularity(&self) -> ConfidenceGranularity {
            ConfidenceGranularity::UtteranceLevel
        }
    }

    #[test]
    fn a_backend_reporting_only_utterance_level_confidence_is_rejected_at_startup() {
        let result =
            ParticipantTokenStreams::new(UtteranceLevelOnlyFactory, InMemoryUtteranceTable::new());

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

        assert!(ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new()).is_ok());
    }

    #[test]
    fn each_participant_gets_its_own_socket() {
        let (factory, opened, _closed) = MockFactory::new();
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

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
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

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
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

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
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

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
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

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

    #[test]
    fn a_finalized_event_is_recorded_in_the_utterances_table_by_the_time_dispatch_returns() {
        let factory = MockFactory::new_finalizing();
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

        let events = streams.dispatch(&"alice".to_string(), &[0; 5]);

        // By the time `dispatch` has returned, the table already holds the
        // exact event handed back to the caller -- not a copy racing to
        // catch up, the same value.
        assert_eq!(events.len(), 1);
        assert!(events[0].is_final);
        let rows = streams.table().rows();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].token(), &events[0]);
    }

    #[test]
    fn partial_events_are_never_written_to_the_utterances_table() {
        let (factory, _opened, _closed) = MockFactory::new();
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

        let events = streams.dispatch(&"alice".to_string(), &[0; 5]);

        assert!(!events[0].is_final);
        assert!(
            streams.table().rows().is_empty(),
            "a partial token must never appear in the append-only utterances table"
        );
    }

    #[test]
    fn finalized_events_from_every_participant_accumulate_in_the_same_table() {
        let factory = MockFactory::new_finalizing();
        let mut streams = ParticipantTokenStreams::new(factory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

        streams.dispatch(&"alice".to_string(), &[0; 3]);
        streams.dispatch(&"bob".to_string(), &[0; 3]);

        let rows = streams.table().rows();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].token().participant_id, "alice");
        assert_eq!(rows[1].token().participant_id, "bob");
    }

    #[test]
    fn a_single_dispatch_call_persists_only_the_final_events_it_returned_in_order() {
        let mut streams = ParticipantTokenStreams::new(MixedFactory, InMemoryUtteranceTable::new())
            .expect("factory reports per-token confidence");

        let events = streams.dispatch(&"alice".to_string(), &[0; 1]);

        // The caller sees all four events, partial and final alike...
        assert_eq!(events.len(), 4);
        // ...but the table holds only the two that were actually final, in
        // the same relative order they were returned, with nothing dropped
        // and nothing duplicated.
        let rows = streams.table().rows();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].token().text, "we need");
        assert_eq!(rows[1].token().text, "to ship");
        assert!(rows.iter().all(|row| row.token().is_final));
    }
}
