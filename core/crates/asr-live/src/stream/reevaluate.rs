//! [`UtteranceReevaluator`] — the piece that makes the trigger gate's
//! tolerance for premature endpoints (architecture §14.2) an actual
//! behaviour rather than just a documented expectation.
//!
//! Aggressive endpointing tuning (moving a silence timer from 600ms to
//! 400ms, or lowering a confidence-based turn model's threshold) buys
//! latency at the cost of cutting utterances mid-sentence more often. When
//! the speaker resumes shortly after, the backend finalises what looks
//! like a brand new, independent utterance — but it is really the second
//! half of the one the gate already saw. This module turns that pair back
//! into one corrected utterance before anything downstream reacts to it
//! twice.

use std::collections::HashMap;
use std::time::Duration;

use crate::backend::{FinalUtterance, StreamId, TranscriptionEvent};

use super::event::StreamEvent;

/// How soon a new finalised utterance has to start after the previous one
/// ended, on the same stream, to be treated as its continuation rather
/// than an independent utterance. Set above `max_turn_silence`'s
/// documented range (1280-1536ms, architecture §14.2): a genuine premature
/// endpoint's gap is bounded by whatever silence threshold caused it, and
/// the forced-end ceiling is the largest that threshold can be, so a
/// window past it catches the pause without also catching a real turn
/// change.
pub const DEFAULT_CONTINUATION_WINDOW: Duration = Duration::from_millis(1600);

/// Re-evaluates finalised utterances on arrival: holds the most recent
/// `Final` per stream, and when the next one starts within
/// `continuation_window` of it, merges the two into one corrected
/// utterance instead of letting the second stand alone. Interims are never
/// held — they pass straight through unchanged, since only a `Final` can
/// turn out to have been premature.
pub struct UtteranceReevaluator {
    continuation_window: Duration,
    last_final: HashMap<StreamId, FinalUtterance>,
}

impl UtteranceReevaluator {
    pub fn new(continuation_window: Duration) -> Self {
        Self { continuation_window, last_final: HashMap::new() }
    }

    /// Feeds one backend event through re-evaluation, returning the event a
    /// downstream consumer should react to instead of the raw backend
    /// output.
    pub fn apply(&mut self, event: TranscriptionEvent) -> StreamEvent {
        match event {
            TranscriptionEvent::Interim(interim) => StreamEvent::Interim(interim),
            TranscriptionEvent::Final(final_utterance) => self.reevaluate(final_utterance),
        }
    }

    fn reevaluate(&mut self, final_utterance: FinalUtterance) -> StreamEvent {
        let continuation = self
            .last_final
            .get(&final_utterance.stream_id)
            .filter(|prior| gap_between(prior, &final_utterance) <= self.continuation_window)
            .cloned();

        let (event, latest) = match continuation {
            Some(prior) => {
                let merged = merge(&prior, &final_utterance);
                (
                    StreamEvent::Correction { supersedes: prior.id, utterance: merged.clone() },
                    merged,
                )
            }
            None => (StreamEvent::Final(final_utterance.clone()), final_utterance),
        };

        self.last_final.insert(latest.stream_id.clone(), latest);
        event
    }
}

impl Default for UtteranceReevaluator {
    fn default() -> Self {
        Self::new(DEFAULT_CONTINUATION_WINDOW)
    }
}

/// Gap between the end of `prior` and the start of `next`, saturating to
/// zero rather than underflowing when a vendor's timestamps overlap by a
/// frame or two at the boundary.
fn gap_between(prior: &FinalUtterance, next: &FinalUtterance) -> Duration {
    next.start.checked_sub(prior.end).unwrap_or(Duration::ZERO)
}

/// Combines a premature endpoint with its continuation into one utterance:
/// text and tokens concatenated in order, spanning from the first's start
/// to the second's end. `id` and `stream_id` come from `next` since that is
/// the finalisation event that actually closed the merged span; `speaker`
/// and `audio_ref` come from `prior` since both halves are the same
/// speaker's one uninterrupted turn. Kept a free function, not a method, so
/// it can be unit-tested against hand-built utterances without a
/// reevaluator.
fn merge(prior: &FinalUtterance, next: &FinalUtterance) -> FinalUtterance {
    FinalUtterance {
        id: next.id.clone(),
        stream_id: next.stream_id.clone(),
        speaker: prior.speaker.clone(),
        text: format!("{} {}", prior.text, next.text),
        start: prior.start,
        end: next.end,
        tokens: prior.tokens.iter().chain(next.tokens.iter()).cloned().collect(),
        audio_ref: prior.audio_ref.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::{AudioSegmentRef, InterimHypothesis, SpeakerTag, Token};

    fn token(text: &str) -> Token {
        Token { text: text.to_string(), confidence: 0.9, lang: "en".to_string(), lang_confidence: 0.99 }
    }

    fn final_utterance(id: &str, stream_id: &str, text: &str, start_ms: u64, end_ms: u64) -> FinalUtterance {
        FinalUtterance {
            id: id.to_string(),
            stream_id: stream_id.to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            text: text.to_string(),
            start: Duration::from_millis(start_ms),
            end: Duration::from_millis(end_ms),
            tokens: text.split_whitespace().map(token).collect(),
            audio_ref: AudioSegmentRef { storage_key: format!("seg-{id}") },
        }
    }

    #[test]
    fn a_continuation_within_the_window_emits_a_correction_merging_both_halves() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        let first = final_utterance("utt-0", "stream-1", "we need to", 0, 600);
        let first_event = reevaluator.apply(TranscriptionEvent::Final(first));
        assert_eq!(
            first_event,
            StreamEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600))
        );

        let continuation = final_utterance("utt-1", "stream-1", "figure out the budget", 900, 1800);
        let second_event = reevaluator.apply(TranscriptionEvent::Final(continuation));

        match second_event {
            StreamEvent::Correction { supersedes, utterance } => {
                assert_eq!(supersedes, "utt-0");
                assert_eq!(utterance.id, "utt-1");
                assert_eq!(utterance.text, "we need to figure out the budget");
                assert_eq!(utterance.start, Duration::from_millis(0));
                assert_eq!(utterance.end, Duration::from_millis(1800));
                assert_eq!(utterance.tokens.len(), 7);
            }
            other => panic!("expected a Correction, got {other:?}"),
        }
    }

    #[test]
    fn a_gap_past_the_window_leaves_both_utterances_independent() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        reevaluator.apply(TranscriptionEvent::Final(final_utterance(
            "utt-0", "stream-1", "we need to figure out the budget", 0, 1800,
        )));

        let unrelated = final_utterance("utt-1", "stream-1", "someone should own this", 5000, 6000);
        let event = reevaluator.apply(TranscriptionEvent::Final(unrelated.clone()));

        assert_eq!(event, StreamEvent::Final(unrelated));
    }

    #[test]
    fn a_gap_exactly_at_the_window_boundary_still_counts_as_a_continuation() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600)));

        let continuation = final_utterance("utt-1", "stream-1", "figure it out", 2200, 3000);
        let event = reevaluator.apply(TranscriptionEvent::Final(continuation));

        assert!(matches!(event, StreamEvent::Correction { .. }), "gap of exactly 1600ms should still merge");
    }

    #[test]
    fn a_gap_one_millisecond_past_the_window_does_not_merge() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600)));

        let independent = final_utterance("utt-1", "stream-1", "figure it out", 2201, 3000);
        let event = reevaluator.apply(TranscriptionEvent::Final(independent.clone()));

        assert_eq!(event, StreamEvent::Final(independent));
    }

    #[test]
    fn a_second_continuation_supersedes_the_first_corrections_id_not_the_original() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600)));
        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-1", "stream-1", "figure out", 900, 1500)));

        let third = final_utterance("utt-2", "stream-1", "the budget", 2000, 2600);
        let event = reevaluator.apply(TranscriptionEvent::Final(third));

        match event {
            StreamEvent::Correction { supersedes, utterance } => {
                assert_eq!(supersedes, "utt-1", "should chase the latest merged id, not the original utt-0");
                assert_eq!(utterance.text, "we need to figure out the budget");
            }
            other => panic!("expected a Correction, got {other:?}"),
        }
    }

    #[test]
    fn distinct_streams_never_merge_across_each_other() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600)));

        let other_stream = final_utterance("utt-1", "stream-2", "figure out the budget", 900, 1800);
        let event = reevaluator.apply(TranscriptionEvent::Final(other_stream.clone()));

        assert_eq!(event, StreamEvent::Final(other_stream));
    }

    #[test]
    fn interims_pass_through_unchanged_and_are_never_held() {
        let mut reevaluator = UtteranceReevaluator::new(Duration::from_millis(1600));

        let interim = InterimHypothesis {
            stream_id: "stream-1".to_string(),
            text: "we need".to_string(),
            started_at: Duration::from_millis(0),
        };
        let event = reevaluator.apply(TranscriptionEvent::Interim(interim.clone()));

        assert_eq!(event, StreamEvent::Interim(interim));
    }

    #[test]
    fn default_reevaluator_uses_the_documented_default_window() {
        let mut reevaluator = UtteranceReevaluator::default();

        reevaluator.apply(TranscriptionEvent::Final(final_utterance("utt-0", "stream-1", "we need to", 0, 600)));
        let continuation = final_utterance("utt-1", "stream-1", "figure it out", 600 + 1600, 3000);
        let event = reevaluator.apply(TranscriptionEvent::Final(continuation));

        assert!(matches!(event, StreamEvent::Correction { .. }));
    }
}
