//! Whether two transcription engines actually fail differently.
//!
//! The record path runs two engines and treats every span they disagree on as
//! a place a human should look. That design rests on an assumption nobody had
//! ever measured: that the two engines make *different* mistakes. Two engines
//! that fail the same way agree with each other, flag nothing, and hand the
//! reviewer a clean-looking transcript with the same errors in it — which is
//! strictly worse than running one engine, because it manufactures confidence.
//!
//! This module measures the assumption. Given a reference transcript and both
//! engines' hypotheses, it reports how the errors are distributed:
//!
//! * **caught** — exactly one engine got it wrong. The engines disagree here,
//!   so the reviewer sees it. This is the value the second engine buys.
//! * **missed** — *both* engines got it wrong. They agree, nothing is flagged,
//!   and the error reaches the debrief unchallenged. This is the number that
//!   matters, and no amount of low per-engine WER makes it safe.
//! * **agreed correct** — both right, nothing to do.
//!
//! # What the number means
//!
//! [`IndependenceReport::catch_rate`] is caught ÷ (caught + missed): of all
//! the errors made, the share the pairing actually surfaces. A catch rate near
//! 1.0 means the engines are close to independent and the second one is
//! earning its cost. Near 0.0 means they fail together — the pairing is
//! decoration, and the honest response is to replace one engine rather than
//! to keep reporting a divergence count that was always going to be low.
//!
//! Deliberately *not* expressed as a correlation coefficient. The question a
//! reviewer asks is "how many of the mistakes will I be shown", and a catch
//! rate answers it in those words; a correlation needs translating before it
//! can be acted on, and translations get skipped.

/// One reference token and what each engine heard for it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenComparison<'a> {
    pub reference: &'a str,
    pub first: &'a str,
    pub second: &'a str,
}

/// How two engines' errors are distributed against a reference.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct IndependenceReport {
    /// Both engines matched the reference.
    pub agreed_correct: usize,
    /// Exactly one engine erred — the disagreement is surfaced for review.
    pub caught: usize,
    /// Both engines erred. Nothing is flagged; the error reaches the debrief.
    pub missed: usize,
}

impl IndependenceReport {
    /// Every token compared.
    pub fn total(&self) -> usize {
        self.agreed_correct + self.caught + self.missed
    }

    /// Errors made by at least one engine.
    pub fn errors(&self) -> usize {
        self.caught + self.missed
    }

    /// The share of errors this pairing surfaces, in `[0, 1]`.
    ///
    /// `None` when there were no errors at all: a catch rate over an empty
    /// error set is not 1.0 (nothing was caught) and not 0.0 (nothing was
    /// missed) — it is undefined, and returning a number here would let a
    /// flawless sample masquerade as evidence of independence.
    pub fn catch_rate(&self) -> Option<f32> {
        (self.errors() > 0).then(|| self.caught as f32 / self.errors() as f32)
    }

    /// Whether this pairing is worth running, at `bar`.
    ///
    /// Answers `false` for an undefined catch rate. A sample with no errors
    /// says nothing about how the engines behave when there are errors, and
    /// treating "no evidence" as "passed" is how an unvalidated assumption
    /// survives review.
    pub fn is_independent_enough(&self, bar: f32) -> bool {
        self.catch_rate().is_some_and(|rate| rate >= bar)
    }

    /// A line for the run log, stating the finding rather than the raw counts.
    pub fn summary(&self) -> String {
        match self.catch_rate() {
            None => format!(
                "engine independence: undetermined — no errors in {} tokens, \
                 so this sample cannot tell whether the engines fail together",
                self.total()
            ),
            Some(rate) => format!(
                "engine independence: {:.1}% of errors surfaced ({} caught, {} missed \
                 by both) across {} tokens",
                rate * 100.0,
                self.caught,
                self.missed,
                self.total()
            ),
        }
    }
}

/// Measures how independently two engines fail against a shared reference.
pub fn measure_independence<'a>(
    comparisons: impl IntoIterator<Item = TokenComparison<'a>>,
) -> IndependenceReport {
    let mut report = IndependenceReport::default();

    for comparison in comparisons {
        let first_wrong = comparison.first != comparison.reference;
        let second_wrong = comparison.second != comparison.reference;

        match (first_wrong, second_wrong) {
            (false, false) => report.agreed_correct += 1,
            // The case the whole record path depends on: they disagree, so
            // the reviewer is shown the span.
            (true, false) | (false, true) => report.caught += 1,
            // Both wrong. Note this counts even when the two engines produced
            // *different* wrong answers: the reviewer is shown a divergence,
            // but neither option offered is right, so the correct reading is
            // not on screen. Counting that as caught would flatter the
            // pairing at exactly the point it fails.
            (true, true) => report.missed += 1,
        }
    }

    report
}

#[cfg(test)]
mod tests {
    use super::*;

    fn compare<'a>(rows: &[(&'a str, &'a str, &'a str)]) -> IndependenceReport {
        measure_independence(rows.iter().map(|(reference, first, second)| TokenComparison {
            reference,
            first,
            second,
        }))
    }

    #[test]
    fn engines_that_fail_differently_surface_every_error() {
        let report = compare(&[
            ("three", "three", "three"),
            ("hundred", "hundred", "hundred"),
            ("fifty", "fifty", "sixty"),
            ("orders", "order", "orders"),
        ]);

        assert_eq!(report.caught, 2);
        assert_eq!(report.missed, 0);
        assert_eq!(report.catch_rate(), Some(1.0));
        assert!(report.is_independent_enough(0.9));
    }

    #[test]
    fn engines_that_fail_together_surface_nothing() {
        // The failure this module exists to detect. Both engines mishear the
        // same numbers, agree with each other, and the reviewer is shown a
        // clean transcript with the numbers wrong in it.
        let report = compare(&[
            ("three", "three", "three"),
            ("fifty", "fifteen", "fifteen"),
            ("orders", "orders", "orders"),
        ]);

        assert_eq!(report.caught, 0);
        assert_eq!(report.missed, 1);
        assert_eq!(report.catch_rate(), Some(0.0));
        assert!(!report.is_independent_enough(0.5));
    }

    #[test]
    fn both_wrong_differently_still_counts_as_missed() {
        // A divergence is shown, but neither reading on screen is correct, so
        // the reviewer cannot pick the right one. Counting this as caught
        // would flatter the pairing exactly where it fails.
        let report = compare(&[("fifty", "fifteen", "sixty")]);

        assert_eq!(report.caught, 0);
        assert_eq!(report.missed, 1);
    }

    #[test]
    fn a_flawless_sample_is_undetermined_rather_than_perfect() {
        // The trap: a clean recording would otherwise "prove" independence
        // while containing no evidence about it whatsoever.
        let report = compare(&[("three", "three", "three"), ("orders", "orders", "orders")]);

        assert_eq!(report.catch_rate(), None);
        assert!(!report.is_independent_enough(0.0), "no evidence is not a pass");
        assert!(report.summary().contains("undetermined"));
    }

    #[test]
    fn an_empty_sample_claims_nothing() {
        let report = compare(&[]);

        assert_eq!(report.total(), 0);
        assert_eq!(report.catch_rate(), None);
        assert!(!report.is_independent_enough(0.0));
    }

    #[test]
    fn the_summary_states_the_finding_not_the_raw_counts() {
        let report = compare(&[("fifty", "fifteen", "fifty"), ("six", "six", "seven")]);

        let summary = report.summary();
        assert!(summary.contains("100.0% of errors surfaced"), "{summary}");
        assert!(summary.contains("2 caught"), "{summary}");
    }

    #[test]
    fn the_counts_always_account_for_every_token() {
        let report = compare(&[
            ("a", "a", "a"),
            ("b", "x", "b"),
            ("c", "x", "y"),
            ("d", "d", "z"),
        ]);

        assert_eq!(report.total(), 4);
        assert_eq!(report.agreed_correct, 1);
        assert_eq!(report.caught, 2);
        assert_eq!(report.missed, 1);
    }
}
