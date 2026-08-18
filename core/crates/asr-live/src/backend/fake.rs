//! Two scripted fake vendors used to prove the trait's central property:
//! whatever the two real target vendors do to produce a partial —
//! AssemblyAI appends immutable partials, Deepgram revises them in place
//! (architecture §3.2) — both project onto the exact same
//! [`TranscriptionEvent`] shape once translated through
//! [`TranscriptionBackend::poll_events`].
//!
//! Neither type here talks to a network; both are frame-scripted so tests
//! stay deterministic without a real vendor connection. They are exported
//! (not `#[cfg(test)]`-only) so a caller wiring up the trigger gate against
//! this trait can exercise it without standing up a real vendor either.

use std::collections::VecDeque;
use std::time::Duration;

use super::event::{
    AudioSegmentRef, FinalUtterance, InterimHypothesis, SpeakerTag, StreamId, Token,
    TranscriptionEvent,
};
use super::transcription_backend::{BackendError, TranscriptionBackend};

/// One vendor "turn": an interim hypothesis followed eventually by a final
/// utterance. Both fakes below are scripted from the same list of turns, so
/// any difference in their emitted event stream is a bug in one of them,
/// not a difference in the test fixture.
struct ScriptedTurn {
    interim_text: &'static str,
    final_text: &'static str,
}

fn sample_script() -> Vec<ScriptedTurn> {
    vec![
        ScriptedTurn { interim_text: "we need", final_text: "we need it fast" },
        ScriptedTurn { interim_text: "someone should", final_text: "someone should own this" },
    ]
}

fn final_utterance(
    turn_index: usize,
    stream_id: &StreamId,
    text: &str,
    start_ms: u64,
    end_ms: u64,
) -> FinalUtterance {
    FinalUtterance {
        id: format!("utt-{turn_index}"),
        stream_id: stream_id.clone(),
        speaker: SpeakerTag::Unknown,
        text: text.to_string(),
        start: Duration::from_millis(start_ms),
        end: Duration::from_millis(end_ms),
        tokens: text
            .split_whitespace()
            .map(|word| Token {
                text: word.to_string(),
                confidence: 0.95,
                lang: "en".to_string(),
                lang_confidence: 0.99,
            })
            .collect(),
        audio_ref: AudioSegmentRef { storage_key: format!("seg-{turn_index}") },
    }
}

/// Mimics a vendor whose streaming output is immutable: once an interim
/// hypothesis is sent for a turn, nothing later rewrites it — the next
/// event for that turn is the final utterance (architecture §3.2, the
/// property AssemblyAI's streaming tier is built around).
pub struct ImmutablePartialFakeBackend {
    pending: VecDeque<TranscriptionEvent>,
    turn: usize,
    script: Vec<ScriptedTurn>,
    frames_per_turn: u64,
    frame_count: u64,
}

impl ImmutablePartialFakeBackend {
    pub fn new() -> Self {
        Self {
            pending: VecDeque::new(),
            turn: 0,
            script: sample_script(),
            frames_per_turn: 2,
            frame_count: 0,
        }
    }
}

impl Default for ImmutablePartialFakeBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl TranscriptionBackend for ImmutablePartialFakeBackend {
    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        if frame.is_empty() {
            return Err(BackendError("empty frame".to_string()));
        }
        self.frame_count += 1;
        if self.turn >= self.script.len() {
            return Ok(());
        }

        let position_in_turn = self.frame_count % self.frames_per_turn;
        let start_ms = 100 * (self.frame_count - 1);
        let end_ms = 100 * self.frame_count;

        if position_in_turn != 0 {
            let turn = &self.script[self.turn];
            self.pending.push_back(TranscriptionEvent::Interim(InterimHypothesis {
                stream_id: stream_id.clone(),
                text: turn.interim_text.to_string(),
                started_at: Duration::from_millis(start_ms),
            }));
        } else {
            let final_text = self.script[self.turn].final_text;
            self.pending.push_back(TranscriptionEvent::Final(final_utterance(
                self.turn, stream_id, final_text, start_ms, end_ms,
            )));
            self.turn += 1;
        }

        Ok(())
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.pending.drain(..).collect()
    }
}

/// Mimics a vendor whose streaming output revises in place: every frame of
/// a turn re-sends a fresh, longer interim rather than appending one and
/// stopping (architecture §3.2's Deepgram-style behaviour — the one that
/// "needs invalidation logic" on the consumer side unless it's normalised
/// to the same event shape here). Right before finalising, it emits one
/// last revised interim carrying the full final text, then the final
/// utterance itself.
pub struct RevisablePartialFakeBackend {
    pending: VecDeque<TranscriptionEvent>,
    turn: usize,
    script: Vec<ScriptedTurn>,
    frames_per_turn: u64,
    frame_count: u64,
}

impl RevisablePartialFakeBackend {
    pub fn new() -> Self {
        Self {
            pending: VecDeque::new(),
            turn: 0,
            script: sample_script(),
            frames_per_turn: 2,
            frame_count: 0,
        }
    }
}

impl Default for RevisablePartialFakeBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl TranscriptionBackend for RevisablePartialFakeBackend {
    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        if frame.is_empty() {
            return Err(BackendError("empty frame".to_string()));
        }
        self.frame_count += 1;
        if self.turn >= self.script.len() {
            return Ok(());
        }

        let position_in_turn = self.frame_count % self.frames_per_turn;
        let start_ms = 100 * (self.frame_count - 1);
        let end_ms = 100 * self.frame_count;
        let turn_index = self.turn;
        let turn = &self.script[turn_index];

        if position_in_turn != 0 {
            self.pending.push_back(TranscriptionEvent::Interim(InterimHypothesis {
                stream_id: stream_id.clone(),
                text: turn.interim_text.to_string(),
                started_at: Duration::from_millis(start_ms),
            }));
        } else {
            let final_text = turn.final_text;
            self.pending.push_back(TranscriptionEvent::Interim(InterimHypothesis {
                stream_id: stream_id.clone(),
                text: final_text.to_string(),
                started_at: Duration::from_millis(start_ms),
            }));
            self.pending.push_back(TranscriptionEvent::Final(final_utterance(
                turn_index, stream_id, final_text, start_ms, end_ms,
            )));
            self.turn += 1;
        }

        Ok(())
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.pending.drain(..).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Drives `frames` silent audio frames through `backend` and collects
    /// every event it emits — written once, generically over
    /// `impl TranscriptionBackend`, exactly the way the trigger gate would
    /// consume any vendor's backend without knowing which one it is.
    fn drive<B: TranscriptionBackend>(
        backend: &mut B,
        stream_id: &StreamId,
        frames: u64,
    ) -> Vec<TranscriptionEvent> {
        let mut events = Vec::new();
        for _ in 0..frames {
            backend
                .send_audio(stream_id, &[0i16; 320])
                .expect("a non-empty frame should never be rejected");
            events.extend(backend.poll_events());
        }
        events
    }

    fn finals(events: &[TranscriptionEvent]) -> Vec<&FinalUtterance> {
        events
            .iter()
            .filter_map(|event| match event {
                TranscriptionEvent::Final(final_utterance) => Some(final_utterance),
                TranscriptionEvent::Interim(_) => None,
            })
            .collect()
    }

    #[test]
    fn both_vendors_emit_the_same_sequence_of_finalised_utterances() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut immutable = ImmutablePartialFakeBackend::new();
        let mut revisable = RevisablePartialFakeBackend::new();

        let immutable_events = drive(&mut immutable, &stream_id, 4);
        let revisable_events = drive(&mut revisable, &stream_id, 4);

        let immutable_finals = finals(&immutable_events);
        let revisable_finals = finals(&revisable_events);

        assert_eq!(immutable_finals.len(), 2, "both scripted turns should finalise");
        assert_eq!(immutable_finals.len(), revisable_finals.len());

        for (immutable_final, revisable_final) in immutable_finals.iter().zip(revisable_finals.iter())
        {
            assert_eq!(immutable_final.text, revisable_final.text);
            assert_eq!(immutable_final.stream_id, revisable_final.stream_id);
            assert_eq!(immutable_final.tokens.len(), revisable_final.tokens.len());
            for (immutable_token, revisable_token) in
                immutable_final.tokens.iter().zip(revisable_final.tokens.iter())
            {
                assert_eq!(immutable_token.text, revisable_token.text);
                assert_eq!(immutable_token.lang, revisable_token.lang);
            }
        }
    }

    #[test]
    fn vendors_differ_in_interim_cadence_while_still_only_emitting_the_shared_event_shape() {
        // The two fakes deliberately behave differently — one immutable, one
        // revising — so this asserts they diverge on *count*, which proves
        // the fixture isn't accidentally identical, while every event from
        // either one still deserializes as a `TranscriptionEvent` variant
        // with no vendor-specific payload attached.
        let stream_id: StreamId = "stream-1".to_string();
        let mut immutable = ImmutablePartialFakeBackend::new();
        let mut revisable = RevisablePartialFakeBackend::new();

        let immutable_events = drive(&mut immutable, &stream_id, 4);
        let revisable_events = drive(&mut revisable, &stream_id, 4);

        let immutable_interim_count = immutable_events
            .iter()
            .filter(|event| matches!(event, TranscriptionEvent::Interim(_)))
            .count();
        let revisable_interim_count = revisable_events
            .iter()
            .filter(|event| matches!(event, TranscriptionEvent::Interim(_)))
            .count();

        assert_eq!(immutable_interim_count, 2, "immutable fake sends one interim per turn");
        assert_eq!(
            revisable_interim_count, 4,
            "revisable fake sends an extra revision right before each final"
        );
    }

    #[test]
    fn a_consumer_written_once_against_the_trait_works_unchanged_across_vendors() {
        // Stands in for the trigger gate: this function is written exactly
        // once, generic over `impl TranscriptionBackend`, and never named a
        // vendor type — swapping which backend it's called with is the
        // entire test.
        fn count_finalised_utterances<B: TranscriptionBackend>(
            backend: &mut B,
            stream_id: &StreamId,
        ) -> usize {
            finals(&drive(backend, stream_id, 4)).len()
        }

        let stream_id: StreamId = "stream-1".to_string();
        let mut immutable = ImmutablePartialFakeBackend::new();
        let mut revisable = RevisablePartialFakeBackend::new();

        assert_eq!(count_finalised_utterances(&mut immutable, &stream_id), 2);
        assert_eq!(count_finalised_utterances(&mut revisable, &stream_id), 2);
    }

    #[test]
    fn final_utterance_tokens_carry_per_token_confidence_and_language() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = ImmutablePartialFakeBackend::new();

        let events = drive(&mut backend, &stream_id, 2);
        let first_final = finals(&events)[0];

        assert!(!first_final.tokens.is_empty());
        for token in &first_final.tokens {
            assert!(token.confidence > 0.0);
            assert_eq!(token.lang, "en");
            assert!(token.lang_confidence > 0.0);
        }
    }

    #[test]
    fn an_empty_frame_is_rejected_rather_than_silently_producing_no_events() {
        let mut backend = ImmutablePartialFakeBackend::new();
        let stream_id: StreamId = "stream-1".to_string();

        let result = backend.send_audio(&stream_id, &[]);

        assert_eq!(result, Err(BackendError("empty frame".to_string())));
    }
}
