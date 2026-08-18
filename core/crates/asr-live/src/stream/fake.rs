//! A scripted [`TranscriptionBackend`] that reproduces the exact scenario
//! architecture §14.2 describes: an aggressively-tuned silence timer cuts
//! an utterance mid-sentence, the speaker resumes shortly after, and a
//! genuinely separate utterance follows much later. Used to prove
//! [`super::UtteranceReevaluator`] end to end, the way `backend::fake`
//! proves `TranscriptionBackend` itself — scripted rather than networked,
//! so the scenario is deterministic without a real vendor connection.
//! Exported (not `#[cfg(test)]`-only) so a caller wiring up the trigger
//! gate against re-evaluated output can exercise it before a real vendor
//! connection exists.

use std::collections::VecDeque;
use std::time::Duration;

use crate::backend::{
    AudioSegmentRef, BackendError, FinalUtterance, InterimHypothesis, SpeakerTag, StreamId, Token,
    TranscriptionBackend, TranscriptionEvent,
};

enum ScriptedEvent {
    Interim { text: &'static str, started_at_ms: u64 },
    Final { id: &'static str, text: &'static str, start_ms: u64, end_ms: u64 },
}

impl ScriptedEvent {
    fn into_event(self, stream_id: &StreamId) -> TranscriptionEvent {
        match self {
            ScriptedEvent::Interim { text, started_at_ms } => {
                TranscriptionEvent::Interim(InterimHypothesis {
                    stream_id: stream_id.clone(),
                    text: text.to_string(),
                    started_at: Duration::from_millis(started_at_ms),
                })
            }
            ScriptedEvent::Final { id, text, start_ms, end_ms } => {
                TranscriptionEvent::Final(FinalUtterance {
                    id: id.to_string(),
                    stream_id: stream_id.clone(),
                    speaker: SpeakerTag::Participant("client-1".to_string()),
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
                    audio_ref: AudioSegmentRef { storage_key: format!("seg-{id}") },
                })
            }
        }
    }
}

/// Scripted, in order: a premature endpoint at a 400ms-style silence
/// threshold mid-sentence ("we need to"), a continuation that resumes well
/// inside the re-evaluation window and closes the thought ("figure out the
/// budget"), then — after a gap long enough to be a real pause between
/// thoughts rather than a cut-off breath — a wholly unrelated utterance
/// ("someone should own this") that must never be merged into the first.
fn premature_endpoint_script() -> VecDeque<ScriptedEvent> {
    VecDeque::from(vec![
        ScriptedEvent::Interim { text: "we need to", started_at_ms: 0 },
        ScriptedEvent::Final { id: "utt-0", text: "we need to", start_ms: 0, end_ms: 600 },
        ScriptedEvent::Interim { text: "figure out the budget", started_at_ms: 900 },
        ScriptedEvent::Final { id: "utt-1", text: "figure out the budget", start_ms: 900, end_ms: 1800 },
        ScriptedEvent::Interim { text: "someone should", started_at_ms: 5000 },
        ScriptedEvent::Final { id: "utt-2", text: "someone should own this", start_ms: 5000, end_ms: 6000 },
    ])
}

/// Emits exactly one scripted event per non-empty frame pushed to it, until
/// the script is exhausted. Timestamps are authored explicitly rather than
/// derived from frame count (contrast `backend::fake`'s fakes), since this
/// fixture's entire point is the precise gaps between utterances.
pub struct PrematureEndpointFakeBackend {
    pending: VecDeque<TranscriptionEvent>,
    script: VecDeque<ScriptedEvent>,
}

impl PrematureEndpointFakeBackend {
    pub fn new() -> Self {
        Self { pending: VecDeque::new(), script: premature_endpoint_script() }
    }
}

impl Default for PrematureEndpointFakeBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl TranscriptionBackend for PrematureEndpointFakeBackend {
    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        if frame.is_empty() {
            return Err(BackendError("empty frame".to_string()));
        }
        if let Some(scripted) = self.script.pop_front() {
            self.pending.push_back(scripted.into_event(stream_id));
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
    use crate::stream::{StreamEvent, UtteranceReevaluator};

    fn drive(backend: &mut PrematureEndpointFakeBackend, stream_id: &StreamId, frames: u64) -> Vec<TranscriptionEvent> {
        let mut events = Vec::new();
        for _ in 0..frames {
            backend.send_audio(stream_id, &[0i16; 320]).expect("a non-empty frame should never be rejected");
            events.extend(backend.poll_events());
        }
        events
    }

    #[test]
    fn a_continuation_after_a_premature_endpoint_emits_a_corrected_utterance() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = PrematureEndpointFakeBackend::new();
        let mut reevaluator = UtteranceReevaluator::default();

        let backend_events = drive(&mut backend, &stream_id, 6);
        let stream_events: Vec<StreamEvent> =
            backend_events.into_iter().map(|event| reevaluator.apply(event)).collect();

        let corrections: Vec<&StreamEvent> =
            stream_events.iter().filter(|event| matches!(event, StreamEvent::Correction { .. })).collect();
        assert_eq!(corrections.len(), 1, "exactly one continuation should trigger exactly one correction");

        match corrections[0] {
            StreamEvent::Correction { supersedes, utterance } => {
                assert_eq!(supersedes, "utt-0");
                assert_eq!(utterance.text, "we need to figure out the budget");
            }
            _ => unreachable!(),
        }

        let finals: Vec<&FinalUtterance> = stream_events
            .iter()
            .filter_map(|event| match event {
                StreamEvent::Final(final_utterance) => Some(final_utterance),
                _ => None,
            })
            .collect();
        assert_eq!(
            finals.len(),
            2,
            "the premature endpoint's own Final passes through uncorrected when it arrives, and the later unrelated utterance is its own Final too"
        );
        assert_eq!(finals[0].text, "we need to", "the premature endpoint, seen before its continuation arrives");
    }

    #[test]
    fn a_genuinely_separate_utterance_never_gets_merged_into_the_correction() {
        let stream_id: StreamId = "stream-1".to_string();
        let mut backend = PrematureEndpointFakeBackend::new();
        let mut reevaluator = UtteranceReevaluator::default();

        let stream_events: Vec<StreamEvent> =
            drive(&mut backend, &stream_id, 6).into_iter().map(|event| reevaluator.apply(event)).collect();

        let last_final = stream_events
            .iter()
            .rev()
            .find_map(|event| match event {
                StreamEvent::Final(final_utterance) => Some(final_utterance),
                _ => None,
            })
            .expect("the unrelated later utterance should stand on its own as a Final");

        assert_eq!(last_final.id, "utt-2");
        assert_eq!(last_final.text, "someone should own this");
    }
}
