//! Rolling gate pass-rate counter (PRD FR-5.7, architecture §3.5): "gate
//! pass rate must not exceed ~10% of utterances".
//!
//! FR-5.7's budget is phrased as a fraction *of utterances*, not of wall
//! clock time, so the window this counter rolls over is a count of the most
//! recent evaluations — not a duration. A count-based window keeps the rate
//! meaningful whether the meeting is running through a rapid-fire Q&A or a
//! long monologue, where a time-based window would either be starved of
//! observations or drowned in them.
//!
//! [`PassRateCounter`] only counts; it does not itself decide anything from
//! the number it produces. Raising the gate's own thresholds in response to
//! a high pass rate — the self-regulation half of architecture §3.5's "and
//! raises its own thresholds if pass rate exceeds ~10%" — is
//! [`super::regulation::ThresholdRegulator`]'s concern: it consumes
//! [`PassRateCounter::record`]'s return value rather than this module
//! deciding anything from the number it produces.

use std::collections::VecDeque;

use crate::parse::TriggerKind;

/// Tracks how many of the most recent `window` gate evaluations fired
/// versus were suppressed, over a rolling window of evaluations.
#[derive(Debug, Clone)]
pub struct PassRateCounter {
    window: usize,
    outcomes: VecDeque<bool>,
    fired: usize,
}

impl PassRateCounter {
    /// Creates a counter rolling over the most recent `window` evaluations.
    /// `window` of `0` has nowhere to roll, so it is treated as `1` —
    /// the counter always keeps at least the newest observation.
    pub fn new(window: usize) -> Self {
        Self {
            window: window.max(1),
            outcomes: VecDeque::new(),
            fired: 0,
        }
    }

    /// Records one gate evaluation's [`TriggerKind`], evicting the oldest
    /// observation once the window is full, and returns the pass rate over
    /// the window as it stands *after* this observation is folded in — the
    /// "every evaluation emits the current pass rate" contract: callers get
    /// a fresh rate back on every call, not just when polled separately.
    pub fn record(&mut self, kind: &TriggerKind) -> f32 {
        self.record_fired(matches!(kind, TriggerKind::Fired))
    }

    /// Records one gate evaluation's outcome directly — `true` if it fired,
    /// `false` if it was suppressed — for callers that already know the
    /// bare outcome and have no [`TriggerKind`] to hand. Same rolling and
    /// return-value contract as [`Self::record`].
    pub fn record_fired(&mut self, fired: bool) -> f32 {
        if self.outcomes.len() == self.window {
            if let Some(true) = self.outcomes.pop_front() {
                self.fired -= 1;
            }
        }
        self.outcomes.push_back(fired);
        if fired {
            self.fired += 1;
        }

        self.pass_rate()
    }

    /// The current pass rate over the window: fired observations divided by
    /// total observations recorded so far (capped at `window`). `0.0`
    /// before any evaluation has been recorded — an empty window has
    /// nothing to be passing.
    pub fn pass_rate(&self) -> f32 {
        if self.outcomes.is_empty() {
            0.0
        } else {
            self.fired as f32 / self.outcomes.len() as f32
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parse::SuppressionReason;

    fn suppressed() -> TriggerKind {
        TriggerKind::Suppressed(SuppressionReason::SpanConfidenceBelowThreshold {
            confidence: 0.1,
            threshold: 0.6,
        })
    }

    #[test]
    fn a_fresh_counter_has_a_zero_pass_rate() {
        let counter = PassRateCounter::new(10);

        assert_eq!(counter.pass_rate(), 0.0);
    }

    #[test]
    fn every_evaluation_gets_back_the_pass_rate_current_at_that_call() {
        let mut counter = PassRateCounter::new(10);

        assert_eq!(counter.record(&TriggerKind::Fired), 1.0);
        assert_eq!(counter.record(&suppressed()), 0.5);
        assert_eq!(counter.record(&suppressed()), 1.0 / 3.0);
    }

    #[test]
    fn the_window_only_rolls_over_the_most_recent_evaluations() {
        let mut counter = PassRateCounter::new(2);

        counter.record(&TriggerKind::Fired);
        counter.record(&TriggerKind::Fired);
        // Window is now full at [Fired, Fired] -> 1.0. A suppressed
        // evaluation evicts the oldest Fired, leaving [Fired, Suppressed].
        assert_eq!(counter.record(&suppressed()), 0.5);
        // Another suppressed evicts the remaining Fired.
        assert_eq!(counter.record(&suppressed()), 0.0);
    }

    #[test]
    fn a_window_of_zero_is_treated_as_one_rather_than_never_rolling() {
        let mut counter = PassRateCounter::new(0);

        assert_eq!(counter.record(&TriggerKind::Fired), 1.0);
        assert_eq!(counter.record(&suppressed()), 0.0);
    }

    #[test]
    fn record_fired_matches_record_for_bare_outcomes() {
        let mut counter = PassRateCounter::new(10);

        assert_eq!(counter.record_fired(true), 1.0);
        assert_eq!(counter.record_fired(false), 0.5);
    }

    #[test]
    fn an_all_suppressed_window_has_a_zero_pass_rate() {
        let mut counter = PassRateCounter::new(3);

        counter.record(&suppressed());
        counter.record(&suppressed());
        counter.record(&suppressed());

        assert_eq!(counter.pass_rate(), 0.0);
    }

    #[test]
    fn an_all_fired_window_has_a_pass_rate_of_one() {
        let mut counter = PassRateCounter::new(3);

        counter.record(&TriggerKind::Fired);
        counter.record(&TriggerKind::Fired);
        counter.record(&TriggerKind::Fired);

        assert_eq!(counter.pass_rate(), 1.0);
    }
}
