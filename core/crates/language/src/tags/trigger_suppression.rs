//! PRD FR-2.22: a token whose language tag is too unreliable to trust must
//! not reach the deterministic trigger tier — but it also must not vanish
//! silently. `segment::group_by_language` and
//! `trigger_gate::lexicon::router::LexiconRouter::run` both already apply
//! this exact `min_tag_confidence` cutoff at the token-routing layer, and
//! both drop a token that misses it with nothing more than an absence from
//! their output. That mirrors every other confidence gate in this
//! directory (`ParticipantLanguageTags::observe`, `TierDriftMonitor::observe`,
//! `AttendeeLanguagePreferences::observe_meeting`) — all return `None` on a
//! miss, which is correct for trackers that only ever *aggregate* confident
//! observations. It is the wrong shape here: PRD §8.2's silent-misdetection
//! failure mode applies just as much to a trigger that never got a chance to
//! fire as to a mislabelled language, so the deterministic trigger tier's
//! own gate needs to say *why* a token was suppressed, not just that it was.
//!
//! `trigger_gate::parse::SuppressionReason::SpanConfidenceBelowThreshold`
//! already does this for a different signal — NFR-5.6's per-word
//! transcription confidence across an already-matched span. This module is
//! the analogous, observable gate for the signal that runs *before* a span
//! can even be matched: whether the token's language identification itself
//! is trustworthy enough to route to a lexicon at all.

/// One language-tagged token that cleared the deterministic trigger tier's
/// confidence gate (PRD FR-2.22).
#[derive(Debug, Clone, PartialEq)]
pub struct GatedLanguageTag {
    /// BCP-47 primary subtag, e.g. `"en"` or `"zh"`.
    pub language: String,
    pub confidence: f32,
}

/// Why a candidate token's language tag failed to clear the deterministic
/// trigger tier's confidence gate.
#[derive(Debug, Clone, PartialEq)]
pub enum TriggerSuppressionReason {
    /// PRD FR-2.22: the token's own language-tag confidence fell below
    /// `threshold`. Routing an unreliably-tagged token to a lexicon anyway
    /// risks scanning it under the wrong language's word list entirely —
    /// this gate prevents that for the cost of one comparison, the same
    /// rationale `trigger_gate::parse::gate::gate_span_confidence` gives for
    /// NFR-5.6's span-confidence gate.
    LanguageTagConfidenceBelowThreshold { language: String, confidence: f32, threshold: f32 },
}

/// The language-tag confidence gate the deterministic trigger tier applies
/// to every token before it may be grouped and routed to a per-language
/// lexicon (PRD FR-2.22).
///
/// Unlike `segment::group_by_language` and `LexiconRouter::run`, which apply
/// the same cutoff but simply omit a token that misses it, `evaluate`
/// returns the [`TriggerSuppressionReason`] instead of a bare `None` — so a
/// caller that wants the suppression to be observable (logged, surfaced to
/// an operator, counted) has something to report, rather than having to
/// infer "suppressed" from an absence that looks identical to "never
/// considered".
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DeterministicTriggerGate {
    min_confidence: f32,
}

impl Default for DeterministicTriggerGate {
    fn default() -> Self {
        DeterministicTriggerGate { min_confidence: 0.6 }
    }
}

impl DeterministicTriggerGate {
    pub fn new() -> Self {
        DeterministicTriggerGate::default()
    }

    /// Overrides the default minimum tag confidence.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// Evaluates one token's `language`/`confidence` tag against this gate.
    /// At or above `min_confidence`, the tag clears the gate and `Ok` carries
    /// it forward (BCP-47 primary subtag, confidence unchanged). Below
    /// threshold, `Err` carries the suppression reason instead of the token
    /// being dropped without explanation.
    pub fn evaluate(
        &self,
        language: &str,
        confidence: f32,
    ) -> Result<GatedLanguageTag, TriggerSuppressionReason> {
        if confidence < self.min_confidence {
            return Err(TriggerSuppressionReason::LanguageTagConfidenceBelowThreshold {
                language: primary_subtag(language),
                confidence,
                threshold: self.min_confidence,
            });
        }

        Ok(GatedLanguageTag { language: primary_subtag(language), confidence })
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" gate
/// the same way. Matches the convention already used by
/// `tags::participant::primary_subtag` and `segment::group_by_language`;
/// duplicated locally rather than imported since neither exposes it.
fn primary_subtag(language: &str) -> String {
    language
        .split(['-', '_'])
        .next()
        .unwrap_or(language)
        .to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_tag_at_or_above_threshold_clears_the_gate() {
        let gate = DeterministicTriggerGate::new();

        assert_eq!(
            gate.evaluate("en", 0.9),
            Ok(GatedLanguageTag { language: "en".to_string(), confidence: 0.9 })
        );
    }

    #[test]
    fn confidence_exactly_at_the_threshold_clears_the_gate() {
        let gate = DeterministicTriggerGate::new();

        assert_eq!(
            gate.evaluate("en", 0.6),
            Ok(GatedLanguageTag { language: "en".to_string(), confidence: 0.6 })
        );
    }

    #[test]
    fn a_low_confidence_tag_is_suppressed_with_its_reason() {
        let gate = DeterministicTriggerGate::new();

        assert_eq!(
            gate.evaluate("en", 0.2),
            Err(TriggerSuppressionReason::LanguageTagConfidenceBelowThreshold {
                language: "en".to_string(),
                confidence: 0.2,
                threshold: 0.6,
            })
        );
    }

    #[test]
    fn suppression_reason_carries_the_language_that_was_suppressed() {
        let gate = DeterministicTriggerGate::new();

        match gate.evaluate("zh", 0.1) {
            Err(TriggerSuppressionReason::LanguageTagConfidenceBelowThreshold {
                language, ..
            }) => assert_eq!(language, "zh"),
            other => panic!("expected a suppression reason, got {other:?}"),
        }
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_before_gating() {
        let gate = DeterministicTriggerGate::new();

        assert_eq!(gate.evaluate("en-US", 0.9).unwrap().language, "en");

        assert_eq!(
            gate.evaluate("ZH-Hans", 0.1),
            Err(TriggerSuppressionReason::LanguageTagConfidenceBelowThreshold {
                language: "zh".to_string(),
                confidence: 0.1,
                threshold: 0.6,
            })
        );
    }

    #[test]
    fn custom_confidence_threshold_gates_evaluation() {
        let gate = DeterministicTriggerGate::new().with_min_confidence(0.95);

        assert!(gate.evaluate("en", 0.9).is_err());
        assert!(gate.evaluate("en", 0.96).is_ok());
    }

    #[test]
    fn a_zero_threshold_never_suppresses() {
        let gate = DeterministicTriggerGate::new().with_min_confidence(0.0);

        assert!(gate.evaluate("en", 0.0).is_ok());
    }

    #[test]
    fn default_min_confidence_matches_every_other_gate_in_this_directory() {
        assert_eq!(DeterministicTriggerGate::default(), DeterministicTriggerGate::new());
        assert!(DeterministicTriggerGate::new().evaluate("en", 0.6).is_ok());
        assert!(DeterministicTriggerGate::new().evaluate("en", 0.59).is_err());
    }
}
