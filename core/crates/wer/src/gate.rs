//! Record-path and live-path accuracy gates (PRD NFR-5.2 through NFR-5.5).
//!
//! [`score_run`](crate::score_run) publishes the entity-weighted WER figure
//! per language and capture-mode partition (NFR-5.7); this module is the
//! consumer that turns that figure into a pass/fail verdict.
//!
//! [`RecordPathGate`] covers the record path, which runs offline, after the
//! meeting, with two engines reconciled against each other (architecture
//! §3.2), which is why it can be held to a materially tighter bar: 3% for
//! Tier 1 languages, 6% for Tier 2 (NFR-5.4, NFR-5.5; architecture "Accuracy
//! bar" table). Every artifact, citation, and coverage decision derives from
//! the record path and never from the live one (architecture §3.2), so this
//! gate is the enforcement point that keeps a signed PRD from silently
//! resting on a transcript that missed its bar.
//!
//! [`LivePathGate`] covers the live path, which runs online during the
//! meeting with no second engine to reconcile against, and so is held to a
//! looser bar than the record path: 8% monolingual (NFR-5.2). A
//! code-switched utterance is gated separately, against its own 15% bar
//! (NFR-5.3) rather than sharing the monolingual live bar — code-switching
//! multiplies the ways a single-language decoding pass can miss an entity,
//! so folding it into the monolingual figure would either mask
//! code-switched failures or needlessly fail clean monolingual audio.

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

/// Whether a live-path partition mixed languages within the same utterance
/// (code-switched, NFR-5.3) or stayed in one language throughout
/// (monolingual, NFR-5.2). Partition `score_run`'s pairs by this before
/// gating, the same way record-path partitions split by [`LanguageTier`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CaptureMode {
    Monolingual,
    CodeSwitched,
}

/// Maximum entity-weighted WER live audio may post and still clear its
/// capture mode's bar: 8% monolingual (NFR-5.2), 15% code-switched
/// (NFR-5.3) — a separate, looser bar rather than a shared live-path figure.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LivePathBar {
    pub monolingual_max: f32,
    pub code_switched_max: f32,
}

impl Default for LivePathBar {
    fn default() -> Self {
        Self {
            monolingual_max: 0.08,
            code_switched_max: 0.15,
        }
    }
}

impl LivePathBar {
    fn max_for(&self, mode: CaptureMode) -> f32 {
        match mode {
            CaptureMode::Monolingual => self.monolingual_max,
            CaptureMode::CodeSwitched => self.code_switched_max,
        }
    }
}

/// Result of gating one language/capture-mode partition's [`RunReport`]
/// against the live path's bar for that capture mode. Mirrors
/// [`GateReport`] in shape; kept as a distinct type because the live path's
/// discriminator is capture mode, not language tier.
#[derive(Debug, Clone, PartialEq)]
pub struct LiveGateReport {
    pub language: String,
    pub capture_mode: CaptureMode,
    pub measured_wer: f32,
    pub max_wer: f32,
    pub verdict: Verdict,
}

impl LiveGateReport {
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
            "{} ({:?}) live entity-weighted WER {:.2}% {} the {:.2}% bar",
            self.language,
            self.capture_mode,
            self.measured_wer * 100.0,
            relation,
            self.max_wer * 100.0
        )
    }
}

/// Gates a run's published entity-weighted WER (per language/capture-mode
/// partition, NFR-5.7) against the live path's bar for its capture mode.
#[derive(Debug, Clone, Copy, Default)]
pub struct LivePathGate {
    bar: LivePathBar,
}

impl LivePathGate {
    pub fn new() -> Self {
        Self::default()
    }

    /// Overrides the default bars.
    pub fn with_bar(mut self, bar: LivePathBar) -> Self {
        self.bar = bar;
        self
    }

    /// Evaluates `run`'s published figure for `language` at `mode` against
    /// the live-path bar for that capture mode.
    pub fn evaluate(&self, language: &str, mode: CaptureMode, run: &RunReport) -> LiveGateReport {
        let max_wer = self.bar.max_for(mode);
        let measured_wer = run.entity_weighted_wer;
        let verdict = if measured_wer <= max_wer {
            Verdict::Pass
        } else {
            Verdict::Fail
        };
        LiveGateReport {
            language: language.to_string(),
            capture_mode: mode,
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
    fn monolingual_under_the_8_percent_bar_passes() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.05);
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert!(report.passed());
        assert_eq!(report.max_wer, 0.08);
    }

    #[test]
    fn monolingual_exactly_at_the_8_percent_bar_passes() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.08);
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        assert_eq!(report.verdict, Verdict::Pass);
    }

    #[test]
    fn monolingual_over_the_8_percent_bar_fails() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.081);
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        assert_eq!(report.verdict, Verdict::Fail);
        assert!(!report.passed());
    }

    #[test]
    fn monolingual_message_reports_language_capture_mode_and_percentages() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.081);
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        let message = report.message();
        assert!(message.contains("en"));
        assert!(message.contains("Monolingual"));
        assert!(message.contains("8.10%"));
        assert!(message.contains("8.00%"));
        assert!(message.contains("exceeds"));
    }

    #[test]
    fn evaluates_the_monolingual_wer_a_real_score_run_produces() {
        // End-to-end sanity check against the actual scorer rather than a
        // hand-built RunReport: an exact transcript match should always
        // clear the 8% monolingual bar (NFR-5.2).
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let reference: Vec<String> = "the client will not renew in Q3"
            .split_whitespace()
            .map(str::to_string)
            .collect();
        let pairs: Vec<(&[String], &[String])> = vec![(&reference[..], &reference[..])];
        let run = score_run(pairs, &vocab, &weights);

        let gate = LivePathGate::new();
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert_eq!(report.measured_wer, 0.0);
    }

    #[test]
    fn custom_monolingual_bar_overrides_the_default_threshold() {
        let gate = LivePathGate::new().with_bar(LivePathBar {
            monolingual_max: 0.01,
            code_switched_max: 0.15,
        });
        let run = run_report_with_wer(0.05);
        let report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        assert_eq!(report.verdict, Verdict::Fail);
    }

    #[test]
    fn code_switched_under_the_15_percent_bar_passes() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.10);
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert!(report.passed());
        assert_eq!(report.max_wer, 0.15);
    }

    #[test]
    fn code_switched_exactly_at_the_15_percent_bar_passes() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.15);
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        assert_eq!(report.verdict, Verdict::Pass);
    }

    #[test]
    fn code_switched_over_the_15_percent_bar_fails() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.151);
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        assert_eq!(report.verdict, Verdict::Fail);
        assert!(!report.passed());
    }

    #[test]
    fn code_switched_bar_is_separate_from_and_looser_than_monolingual() {
        let gate = LivePathGate::new();
        // 10% would fail the 8% monolingual bar but clears the 15%
        // code-switched bar — the two capture modes must not share a figure.
        let run = run_report_with_wer(0.10);
        let monolingual_report = gate.evaluate("en", CaptureMode::Monolingual, &run);
        let code_switched_report = gate.evaluate("en", CaptureMode::CodeSwitched, &run);
        assert_eq!(monolingual_report.verdict, Verdict::Fail);
        assert_eq!(code_switched_report.verdict, Verdict::Pass);
    }

    #[test]
    fn custom_live_bar_overrides_the_default_thresholds() {
        let gate = LivePathGate::new().with_bar(LivePathBar {
            monolingual_max: 0.08,
            code_switched_max: 0.05,
        });
        let run = run_report_with_wer(0.10);
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        assert_eq!(report.verdict, Verdict::Fail);
    }

    #[test]
    fn live_message_reports_language_capture_mode_and_percentages() {
        let gate = LivePathGate::new();
        let run = run_report_with_wer(0.151);
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        let message = report.message();
        assert!(message.contains("en-zh"));
        assert!(message.contains("CodeSwitched"));
        assert!(message.contains("15.10%"));
        assert!(message.contains("15.00%"));
        assert!(message.contains("exceeds"));
    }

    #[test]
    fn evaluates_the_code_switched_wer_a_real_score_run_produces() {
        // End-to-end sanity check against the actual scorer rather than a
        // hand-built RunReport: an exact transcript match should always
        // clear the 15% code-switched bar.
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let reference: Vec<String> = "the client will not renew in Q3"
            .split_whitespace()
            .map(str::to_string)
            .collect();
        let pairs: Vec<(&[String], &[String])> = vec![(&reference[..], &reference[..])];
        let run = score_run(pairs, &vocab, &weights);

        let gate = LivePathGate::new();
        let report = gate.evaluate("en-zh", CaptureMode::CodeSwitched, &run);
        assert_eq!(report.verdict, Verdict::Pass);
        assert_eq!(report.measured_wer, 0.0);
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
