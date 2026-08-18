//! Gate self-regulation (PRD FR-5.7, architecture §3.5): "the gate ...
//! raises its own thresholds if pass rate exceeds ~10%".
//!
//! [`PassRateCounter`] only counts the rolling pass rate; it does not decide
//! anything from the number it produces. [`ThresholdRegulator`] is the
//! consumer that closes that loop: it folds every gate evaluation's outcome
//! into a [`PassRateCounter`], and once the rolling pass rate climbs above
//! `excess_pass_rate` (~10% of utterances per FR-5.7), it raises the gate's
//! own confidence threshold and reports a [`RegulationOutcome::ThresholdRaised`]
//! event rather than letting an excessive pass rate keep putting a nudge in
//! front of the client for every evaluation that fires.
//!
//! This is the sibling concern to [`StormGuard`](super::StormGuard): where
//! `StormGuard` reacts to evaluations *arriving* faster than the rolling
//! window could ever react to, `ThresholdRegulator` reacts to the window
//! itself settling at too high a pass rate over the longer run — the two
//! failure modes architecture §3.5's risk table treats as related but
//! distinct, each raising the same kind of response (a higher threshold)
//! from a different signal.

use super::pass_rate::PassRateCounter;
use crate::parse::TriggerKind;

/// What a [`ThresholdRegulator`] decided about one evaluation's outcome.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum RegulationOutcome {
    /// The rolling pass rate is within budget. The caller should keep
    /// gating against `threshold` (the base threshold, or a still-elevated
    /// one left over from an excess that only just subsided).
    Clear { pass_rate: f32, threshold: f32 },
    /// The rolling pass rate exceeds the gate's budget: `pass_rate` of the
    /// evaluations in the window fired. The gate's own confidence threshold
    /// has been raised to `raised_threshold` in response.
    ThresholdRaised { pass_rate: f32, raised_threshold: f32 },
}

/// Watches the rolling gate pass rate and raises the gate's confidence
/// threshold once it exceeds budget, so an excessive pass rate corrects
/// itself instead of flooding the panel with nudges indefinitely.
#[derive(Debug, Clone)]
pub struct ThresholdRegulator {
    counter: PassRateCounter,
    excess_pass_rate: f32,
    base_threshold: f32,
    max_threshold: f32,
    raise_step: f32,
    current_threshold: f32,
}

impl ThresholdRegulator {
    /// Creates a regulator rolling the pass rate over the most recent
    /// `window` evaluations (see [`PassRateCounter::new`]), raising the
    /// gate's confidence threshold from `base_threshold` by `raise_step`
    /// once the pass rate exceeds `excess_pass_rate` — `0.1` for FR-5.7's
    /// ~10%-of-utterances budget — and capping the raised threshold at
    /// `max_threshold`.
    pub fn new(
        window: usize,
        excess_pass_rate: f32,
        base_threshold: f32,
        max_threshold: f32,
        raise_step: f32,
    ) -> Self {
        Self {
            counter: PassRateCounter::new(window),
            excess_pass_rate,
            base_threshold,
            max_threshold,
            raise_step,
            current_threshold: base_threshold,
        }
    }

    /// Records one gate evaluation's [`TriggerKind`], folding it into the
    /// rolling pass rate, and returns whether the gate should keep using its
    /// current threshold or has just had it raised.
    pub fn record(&mut self, kind: &TriggerKind) -> RegulationOutcome {
        self.record_fired(matches!(kind, TriggerKind::Fired))
    }

    /// Records one gate evaluation's outcome directly — `true` if it fired,
    /// `false` if it was suppressed — for callers that already know the
    /// bare outcome and have no [`TriggerKind`] to hand. Same rolling and
    /// return-value contract as [`Self::record`].
    pub fn record_fired(&mut self, fired: bool) -> RegulationOutcome {
        let pass_rate = self.counter.record_fired(fired);

        if pass_rate > self.excess_pass_rate {
            self.current_threshold = (self.current_threshold + self.raise_step).min(self.max_threshold);
            RegulationOutcome::ThresholdRaised {
                pass_rate,
                raised_threshold: self.current_threshold,
            }
        } else {
            // The rolling window already smooths out single observations,
            // so once it reports a pass rate back within budget the excess
            // has genuinely subsided — the threshold relaxes back to
            // baseline rather than staying elevated for the rest of the
            // meeting.
            self.current_threshold = self.base_threshold;
            RegulationOutcome::Clear {
                pass_rate,
                threshold: self.current_threshold,
            }
        }
    }

    /// The confidence threshold the gate should be using right now — the
    /// base threshold, or a raised one if the pass rate is currently in
    /// excess or has only just come back within budget.
    pub fn current_threshold(&self) -> f32 {
        self.current_threshold
    }

    /// The current rolling pass rate, without recording a new evaluation.
    pub fn pass_rate(&self) -> f32 {
        self.counter.pass_rate()
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

    // 0.5, 0.25, and 0.75 are exactly representable in f32, so the raised
    // thresholds below are exact arithmetic rather than an approximation
    // that would need an epsilon comparison (unlike, say, 0.6 + 0.1).

    #[test]
    fn a_pass_rate_within_budget_stays_clear_at_the_base_threshold() {
        let mut regulator = ThresholdRegulator::new(10, 0.1, 0.5, 0.9, 0.25);

        assert_eq!(
            regulator.record(&suppressed()),
            RegulationOutcome::Clear {
                pass_rate: 0.0,
                threshold: 0.5,
            }
        );
        assert_eq!(
            regulator.record(&suppressed()),
            RegulationOutcome::Clear {
                pass_rate: 0.0,
                threshold: 0.5,
            }
        );
    }

    #[test]
    fn an_excessive_pass_rate_raises_the_threshold_and_emits_the_event() {
        let mut regulator = ThresholdRegulator::new(10, 0.1, 0.5, 0.9, 0.25);

        // A single fired evaluation out of one puts the rolling pass rate
        // at 1.0, well past the 10% budget.
        assert_eq!(
            regulator.record(&TriggerKind::Fired),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.75,
            }
        );
    }

    #[test]
    fn the_threshold_keeps_raising_while_the_excess_continues_but_caps_at_max() {
        let mut regulator = ThresholdRegulator::new(10, 0.1, 0.5, 0.9, 0.25);

        assert_eq!(
            regulator.record(&TriggerKind::Fired),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.75,
            }
        );
        // Would be 1.0 uncapped; max_threshold holds it at 0.9.
        assert_eq!(
            regulator.record(&TriggerKind::Fired),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.9,
            }
        );
        assert_eq!(
            regulator.record(&TriggerKind::Fired),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.9,
            }
        );
    }

    #[test]
    fn the_threshold_relaxes_back_to_base_once_the_pass_rate_falls_back_in_budget() {
        let mut regulator = ThresholdRegulator::new(4, 0.1, 0.5, 0.9, 0.25);

        assert_eq!(
            regulator.record(&TriggerKind::Fired),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.75,
            }
        );

        // Three suppressed evaluations dilute the rolling pass rate back to
        // 1/4 = 0.25... still not below 0.1 yet.
        regulator.record(&suppressed());
        regulator.record(&suppressed());
        assert_eq!(
            regulator.record(&suppressed()),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 0.25,
                raised_threshold: 0.9,
            }
        );

        // A 4th suppressed evaluation evicts the original fired one out of
        // the window of 4, bringing the pass rate to 0.0 — back in budget.
        assert_eq!(
            regulator.record(&suppressed()),
            RegulationOutcome::Clear {
                pass_rate: 0.0,
                threshold: 0.5,
            }
        );
    }

    #[test]
    fn exactly_the_excess_pass_rate_is_not_itself_excessive() {
        let mut regulator = ThresholdRegulator::new(10, 0.5, 0.5, 0.9, 0.25);

        // 1 fired out of 2 is exactly 0.5 — at budget, not over it.
        regulator.record(&TriggerKind::Fired);
        assert_eq!(
            regulator.record(&suppressed()),
            RegulationOutcome::Clear {
                pass_rate: 0.5,
                threshold: 0.5,
            }
        );
    }

    #[test]
    fn current_threshold_and_pass_rate_reflect_state_without_recording() {
        let mut regulator = ThresholdRegulator::new(10, 0.1, 0.5, 0.9, 0.25);
        assert_eq!(regulator.current_threshold(), 0.5);
        assert_eq!(regulator.pass_rate(), 0.0);

        regulator.record(&TriggerKind::Fired);
        assert_eq!(regulator.current_threshold(), 0.75);
        assert_eq!(regulator.pass_rate(), 1.0);
    }

    #[test]
    fn record_fired_matches_record_for_bare_outcomes() {
        let mut regulator = ThresholdRegulator::new(10, 0.1, 0.5, 0.9, 0.25);

        assert_eq!(
            regulator.record_fired(true),
            RegulationOutcome::ThresholdRaised {
                pass_rate: 1.0,
                raised_threshold: 0.75,
            }
        );
    }
}
