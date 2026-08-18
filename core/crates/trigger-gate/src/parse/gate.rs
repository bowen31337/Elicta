//! Span-confidence gating (PRD NFR-5.6, architecture §3.5): the last check
//! a candidate trigger span passes through before it is allowed to become a
//! nudge.
//!
//! Per-word confidence lives on the tokens a span was matched from (see
//! `super::super::lexicon::grouping::TaggedToken::confidence`), not on the
//! span as a whole, so [`gate_span_confidence`] takes every word confidence
//! the span covers and reduces it to the minimum itself — matching
//! architecture §3.5's own definition of `TriggerEvent.confidence` as "the
//! minimum token confidence across the span". A multi-word span is only as
//! trustworthy as its least-confident word: one misheard word inside an
//! otherwise clean span is exactly the `quantify "fast"`-for-"vast" case
//! NFR-5.6 exists to catch, so averaging (which a single bad word could not
//! move far) would defeat the point.

use std::ops::Range;

use super::event::{SuppressionReason, TriggerEvent};

/// Gates a candidate trigger `span` — whose byte range and matched text are
/// `lexicon`'s concern, not this function's — against `min_span_confidence`
/// (PRD NFR-5.6). `word_confidences` are the per-word confidences of every
/// token the span covers, in any order; a span backed by zero words has
/// nothing to be confident about and is suppressed with confidence `0.0`
/// rather than treated as automatically trustworthy.
pub fn gate_span_confidence(
    span: Range<usize>,
    word_confidences: &[f32],
    min_span_confidence: f32,
) -> TriggerEvent {
    let confidence = word_confidences
        .iter()
        .copied()
        .fold(f32::INFINITY, f32::min);
    let confidence = if confidence.is_finite() {
        confidence
    } else {
        0.0
    };

    if confidence < min_span_confidence {
        TriggerEvent::Suppressed {
            span,
            confidence,
            reason: SuppressionReason::SpanConfidenceBelowThreshold {
                confidence,
                threshold: min_span_confidence,
            },
        }
    } else {
        TriggerEvent::Fired { span, confidence }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_span_at_or_above_threshold_fires_and_carries_its_own_confidence() {
        let event = gate_span_confidence(4..9, &[0.9, 0.95], 0.6);

        assert_eq!(
            event,
            TriggerEvent::Fired {
                span: 4..9,
                confidence: 0.9,
            }
        );
    }

    #[test]
    fn a_span_below_threshold_is_suppressed_and_carries_its_reason() {
        let event = gate_span_confidence(4..9, &[0.9, 0.3], 0.6);

        assert_eq!(
            event,
            TriggerEvent::Suppressed {
                span: 4..9,
                confidence: 0.3,
                reason: SuppressionReason::SpanConfidenceBelowThreshold {
                    confidence: 0.3,
                    threshold: 0.6,
                },
            }
        );
    }

    #[test]
    fn a_single_low_confidence_word_suppresses_an_otherwise_confident_span() {
        // The `quantify "fast"`-for-"vast" case NFR-5.6 exists to catch:
        // one misheard word inside an otherwise clean multi-word span.
        let event = gate_span_confidence(0..20, &[0.98, 0.97, 0.2, 0.99], 0.6);

        assert!(matches!(
            event,
            TriggerEvent::Suppressed { confidence, .. } if confidence == 0.2
        ));
    }

    #[test]
    fn confidence_exactly_at_the_threshold_is_not_suppressed() {
        let event = gate_span_confidence(0..3, &[0.6], 0.6);

        assert_eq!(
            event,
            TriggerEvent::Fired {
                span: 0..3,
                confidence: 0.6,
            }
        );
    }

    #[test]
    fn a_span_backed_by_no_words_is_suppressed_rather_than_trusted_by_default() {
        let event = gate_span_confidence(0..0, &[], 0.6);

        assert_eq!(
            event,
            TriggerEvent::Suppressed {
                span: 0..0,
                confidence: 0.0,
                reason: SuppressionReason::SpanConfidenceBelowThreshold {
                    confidence: 0.0,
                    threshold: 0.6,
                },
            }
        );
    }

    #[test]
    fn a_zero_threshold_never_suppresses() {
        let event = gate_span_confidence(0..3, &[0.0], 0.0);

        assert_eq!(
            event,
            TriggerEvent::Fired {
                span: 0..3,
                confidence: 0.0,
            }
        );
    }
}
