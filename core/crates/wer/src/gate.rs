//! Record-path accuracy gate (PRD NFR-5.4, NFR-5.5).
//!
//! [`score_run`](crate::score_run) publishes the entity-weighted WER figure
//! per language and capture-mode partition (NFR-5.7); this module is the
//! consumer that turns that figure into a pass/fail verdict for the record
//! path specifically. The record path runs offline, after the meeting, with
//! two engines reconciled against each other (architecture §3.2), which is
//! why it can be held to a materially tighter bar than the live path's 8%
//! monolingual / 15% code-switched figures (NFR-5.2, NFR-5.3): 3% for Tier 1
//! languages, 6% for Tier 2 (architecture "Accuracy bar" table).
//!
//! Every artifact, citation, and coverage decision derives from the record
//! path and never from the live one (architecture §3.2), so this gate is
//! the enforcement point that keeps a signed PRD from silently resting on a
//! transcript that missed its bar.

use crate::score::RunReport;

/// Which support tier a language sits at, for the purpose of the
/// record-path bar it must clear (PRD §8.2a / architecture "Accuracy bar"
/// table). This mirrors `language::tags::LanguageTier` in shape rather than
/// depending on it — the gate only needs to know which bar applies, not the
/// rest of tiering (drift detection, live-accuracy fallback).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum LanguageTier {
    Tier1,
    Tier2,
}

/// Maximum entity-weighted WER a language may post on the record path and
/// still clear its tier's bar (NFR-5.4: 3% for Tier 1; NFR-5.5: 6% for
/// Tier 2).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RecordPathBar {
    pub tier1_max: f32,
    pub tier2_max: f32,
}

impl Default for RecordPathBar {
    fn default() -> Self {
        Self {
            tier1_max: 0.03,
            tier2_max: 0.06,
        }
    }
}

impl RecordPathBar {
    fn max_for(&self, tier: LanguageTier) -> f32 {
        match tier {
            LanguageTier::Tier1 => self.tier1_max,
            LanguageTier::Tier2 => self.tier2_max,
        }
    }
}

/// Pass/fail outcome of one gate evaluation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Pass,
    Fail,
}

/// Result of gating one language/capture-mode partition's [`RunReport`]
/// against its tier's record-path bar. Always produced — passing or
/// failing — since NFR-5.4 requires the bar to be enforced, not merely
/// measured.
#[derive(Debug, Clone, PartialEq)]
pub struct GateReport {
    pub language: String,
    pub tier: LanguageTier,
    pub measured_wer: f32,
    pub max_wer: f32,
    pub verdict: Verdict,
}

impl GateReport {
    pub fn passed(&self) -> bool {
        self.verdict == Verdict::Pass
    }

    /// Operator/CI-facing summary line.
    pub fn message(&self) -> String {
        let relation = match self.verdict {
            Verdict::Pass => "within",
            Verdict::Fail => "exceeds",
        };
        format!(
            "{} ({:?}) record-path entity-weighted WER {:.2}% {} the {:.2}% bar",
            self.language,
            self.tier,
            self.measured_wer * 100.0,
            relation,
            self.max_wer * 100.0
        )
    }
}

/// Gates a run's published entity-weighted WER (per language/capture-mode
/// partition, NFR-5.7) against the record-path bar for its tier.
#[derive(Debug, Clone, Copy, Default)]
pub struct RecordPathGate {
    bar: RecordPathBar,
}

impl RecordPathGate {
    pub fn new() -> Self {
        Self::default()
    }

    /// Overrides the default bars.
    pub fn with_bar(mut self, bar: RecordPathBar) -> Self {
        self.bar = bar;
        self
    }

    /// Evaluates `run`'s published figure for `language` at `tier` against
    /// the record-path bar for that tier.
    pub fn evaluate(&self, language: &str, tier: LanguageTier, run: &RunReport) -> GateReport {
        let max_wer = self.bar.max_for(tier);
        let measured_wer = run.entity_weighted_wer;
        let verdict = if measured_wer <= max_wer {
            Verdict::Pass
        } else {
            Verdict::Fail
        };
        GateReport {
            language: language.to_string(),
            tier,
            measured_wer,
            max_wer,
            verdict,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entity::EngagementVocabulary;
    use crate::score::{score_run, AlignmentWeights};

    fn run_report_with_wer(wer: f32) -> RunReport {
        RunReport {
            entity_weighted_wer: wer,
            utterances_scored: 1,
            weighted_errors: wer,
            weighted_reference_len: 1.0,
        }
    }

    #[test]
    fn tier1_under_the_3_percent_bar_passes() {
        let gate = RecordPathGate::new();
        let run = run_report_with_wer(0.02);
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert!(report.passed());
        assert_eq!(report.max_wer, 0.03);
    }

    #[test]
    fn tier1_exactly_at_the_3_percent_bar_passes() {
        let gate = RecordPathGate::new();
        let run = run_report_with_wer(0.03);
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        assert_eq!(report.verdict, Verdict::Pass);
    }

    #[test]
    fn tier1_over_the_3_percent_bar_fails() {
        let gate = RecordPathGate::new();
        let run = run_report_with_wer(0.031);
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        assert_eq!(report.verdict, Verdict::Fail);
        assert!(!report.passed());
    }

    #[test]
    fn tier2_bar_is_looser_than_tier1() {
        let gate = RecordPathGate::new();
        // 4% would fail Tier 1's 3% bar but clears Tier 2's 6% bar.
        let run = run_report_with_wer(0.04);
        let tier1_report = gate.evaluate("vi", LanguageTier::Tier1, &run);
        let tier2_report = gate.evaluate("vi", LanguageTier::Tier2, &run);
        assert_eq!(tier1_report.verdict, Verdict::Fail);
        assert_eq!(tier2_report.verdict, Verdict::Pass);
    }

    #[test]
    fn custom_bar_overrides_the_default_thresholds() {
        let gate = RecordPathGate::new().with_bar(RecordPathBar {
            tier1_max: 0.01,
            tier2_max: 0.06,
        });
        let run = run_report_with_wer(0.02);
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        assert_eq!(report.verdict, Verdict::Fail);
    }

    #[test]
    fn message_reports_language_tier_and_percentages() {
        let gate = RecordPathGate::new();
        let run = run_report_with_wer(0.031);
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        let message = report.message();
        assert!(message.contains("en"));
        assert!(message.contains("Tier1"));
        assert!(message.contains("3.10%"));
        assert!(message.contains("3.00%"));
        assert!(message.contains("exceeds"));
    }

    #[test]
    fn evaluates_the_wer_a_real_score_run_produces() {
        // End-to-end sanity check against the actual scorer rather than a
        // hand-built RunReport: an exact transcript match should always
        // clear Tier 1's bar.
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let reference: Vec<String> = "the client will not renew in Q3"
            .split_whitespace()
            .map(str::to_string)
            .collect();
        let pairs: Vec<(&[String], &[String])> = vec![(&reference[..], &reference[..])];
        let run = score_run(pairs, &vocab, &weights);

        let gate = RecordPathGate::new();
        let report = gate.evaluate("en", LanguageTier::Tier1, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert_eq!(report.measured_wer, 0.0);
    }
}
