use std::collections::HashMap;
use std::ops::Range;

use super::error::PhrasingError;
use super::slots::format_named;

/// The placeholder name architecture §3.6's own example fills from
/// `TriggerEvent.span` -- `"What's the slowest {term} the {function} team
/// would still accept?"`, where `{term}` is "the client's actual word" and
/// `{function}` comes from the attendee roster instead. This module only
/// ever resolves `{term}`; any other named placeholder in a candidate's
/// phrasing is out of scope here (see [`super`]'s module doc).
pub const SPAN_SLOT: &str = "term";

/// The winning candidate's phrasing, as scored and selected by ranking
/// (architecture §3.7) -- just the `id` and `{slot}`-bearing `phrasing`
/// this module needs, not the full `candidate` row (template section,
/// trigger types, priority, ...), which belongs to whatever scores
/// candidates rather than to instantiating the one that already won.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub id: String,
    pub phrasing: String,
}

/// Fills the winning `candidate`'s `{term}` placeholder with the client's
/// actual wording -- the substring of `utterance_text` at `trigger_span` --
/// and returns the fully formed question string. String interpolation, not
/// inference (ADR-003): no model call sits anywhere on this path, so it
/// stays well inside architecture §5's <5ms slot-instantiation budget.
pub fn instantiate(
    candidate: &Candidate,
    utterance_text: &str,
    trigger_span: Range<usize>,
) -> Result<String, PhrasingError> {
    let wording = extract_span(utterance_text, trigger_span)?;

    let mut values: HashMap<&str, String> = HashMap::with_capacity(1);
    values.insert(SPAN_SLOT, wording.to_string());

    format_named(&candidate.phrasing, &values)
        .map_err(|err| PhrasingError::from_slot_error(&candidate.id, err))
}

/// Slices the client's own wording out of `utterance_text` at `span`,
/// rejecting a span the utterance can't actually back rather than letting
/// the string-slice panic that would otherwise cause.
fn extract_span(utterance_text: &str, span: Range<usize>) -> Result<&str, PhrasingError> {
    if span.start > span.end || span.end > utterance_text.len() {
        return Err(PhrasingError::SpanOutOfBounds {
            span,
            utterance_len: utterance_text.len(),
        });
    }
    if !utterance_text.is_char_boundary(span.start) || !utterance_text.is_char_boundary(span.end) {
        return Err(PhrasingError::SpanNotOnCharBoundary { span });
    }

    Ok(&utterance_text[span])
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    fn candidate(phrasing: &str) -> Candidate {
        Candidate {
            id: "candidate-1".to_string(),
            phrasing: phrasing.to_string(),
        }
    }

    #[test]
    fn interpolates_the_client_wording_from_the_trigger_span_into_the_stored_phrasing() {
        let utterance = "we need it fast";
        let span = utterance
            .find("fast")
            .map(|start| start..start + "fast".len())
            .unwrap();

        let question = instantiate(&candidate("Quantify \"{term}\"."), utterance, span).unwrap();

        assert_eq!(question, "Quantify \"fast\".");
    }

    #[test]
    fn preserves_surrounding_literal_text_around_the_slot() {
        let utterance = "the API needs to be scalable next quarter";
        let span = utterance
            .find("scalable")
            .map(|start| start..start + "scalable".len())
            .unwrap();

        let question = instantiate(
            &candidate("What does \"{term}\" mean in numbers?"),
            utterance,
            span,
        )
        .unwrap();

        assert_eq!(question, "What does \"scalable\" mean in numbers?");
    }

    #[test]
    fn a_span_past_the_end_of_the_utterance_is_rejected_rather_than_panicking() {
        let utterance = "short utterance";
        let err = instantiate(&candidate("{term}"), utterance, 0..1000).unwrap_err();

        assert_eq!(
            err,
            PhrasingError::SpanOutOfBounds {
                span: 0..1000,
                utterance_len: utterance.len(),
            }
        );
    }

    #[test]
    fn a_span_that_splits_a_multi_byte_character_is_rejected_rather_than_panicking() {
        let utterance = "有一些问题";
        // Byte 1 lands inside the first three-byte UTF-8 character.
        let err = instantiate(&candidate("{term}"), utterance, 1..4).unwrap_err();

        assert_eq!(err, PhrasingError::SpanNotOnCharBoundary { span: 1..4 });
    }

    #[test]
    fn a_placeholder_the_trigger_span_cannot_fill_is_rejected_rather_than_guessed_at() {
        let utterance = "we need it fast";
        let span = utterance
            .find("fast")
            .map(|start| start..start + "fast".len())
            .unwrap();

        let err = instantiate(
            &candidate("What's the slowest {term} the {function} team would still accept?"),
            utterance,
            span,
        )
        .unwrap_err();

        assert_eq!(
            err,
            PhrasingError::UnresolvedSlot {
                candidate_id: "candidate-1".to_string(),
                slot: "function".to_string(),
            }
        );
    }

    #[test]
    fn a_malformed_placeholder_is_rejected_rather_than_silently_dropped() {
        let utterance = "we need it fast";
        let span = utterance
            .find("fast")
            .map(|start| start..start + "fast".len())
            .unwrap();

        let err = instantiate(&candidate("Quantify {term."), utterance, span).unwrap_err();

        assert_eq!(
            err,
            PhrasingError::MalformedPlaceholder {
                candidate_id: "candidate-1".to_string(),
            }
        );
    }

    #[test]
    fn stays_inside_the_five_millisecond_slot_instantiation_budget() {
        // Architecture §5's critical path names this step's own figure:
        // "Slot instantiation ─────────────────────── <5ms".
        const SLOT_INSTANTIATION_BUDGET: Duration = Duration::from_millis(5);

        let utterance = "we need it fast, scalable, and user-friendly, and soon";
        let span = utterance
            .find("fast")
            .map(|start| start..start + "fast".len())
            .unwrap();
        let winning_candidate = candidate(
            "What's the slowest {term} the engineering team would still accept, and by when?",
        );

        let start = Instant::now();
        let question = instantiate(&winning_candidate, utterance, span).unwrap();
        let elapsed = start.elapsed();

        assert!(
            question.contains("fast"),
            "the fully formed question must carry the client's actual wording"
        );
        assert!(
            elapsed < SLOT_INSTANTIATION_BUDGET,
            "slot instantiation exceeded its latency budget: {elapsed:?} >= {SLOT_INSTANTIATION_BUDGET:?}"
        );
    }
}
