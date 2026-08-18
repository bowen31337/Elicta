//! Endpointing-storm absorption (architecture §3.5 risk table; PRD FR-5.7,
//! FR-5.8): "Endpointing storm (cross-talk) | Utterance rate threshold |
//! Gate raises thresholds; rate limiter absorbs the rest".
//!
//! Cross-talk makes an ASR backend endpoint prematurely and repeatedly —
//! overlapping speech looks like one speaker stopping and starting many
//! times a second, so the gate is handed a burst of candidate spans to
//! evaluate in quick succession. [`PassRateCounter`](super::PassRateCounter)
//! cannot see this coming: its window rolls over a *count* of evaluations,
//! so a burst dilutes into the average over the following minutes rather
//! than being caught while it is happening. By the time the rolling pass
//! rate would climb high enough to matter, the storm has already put one
//! nudge candidate on the panel for every spurious endpoint.
//!
//! [`StormGuard`] catches the burst at the rate evaluations *arrive*
//! instead. Once arrivals within a short window cross `burst_threshold`, it
//! stops treating each one as an independent candidate: it raises the
//! gate's own confidence threshold — the response the risk table specifies
//! — and reports the burst as a single [`StormOutcome::StormAbsorbed`]
//! event rather than letting every evaluation in it become its own nudge.
//! Once arrivals go quiet for a full window, the storm is over and the
//! threshold relaxes back to where it started.

use std::collections::VecDeque;
use std::time::Duration;

/// What a [`StormGuard`] decided about one evaluation's arrival.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StormOutcome {
    /// Arrivals are under control. The caller should gate this evaluation
    /// normally, against `threshold` (the base confidence threshold, or a
    /// still-elevated one left over from a burst that only just subsided).
    Clear { threshold: f32 },
    /// A cross-talk burst is under way: `burst_len` evaluations have
    /// arrived within the storm window, including this one. This
    /// evaluation should not be gated individually and should not become
    /// its own nudge — fold it into one storm-absorbed event and gate
    /// anything that still comes through against `raised_threshold`.
    StormAbsorbed {
        burst_len: usize,
        raised_threshold: f32,
    },
}

/// Detects an endpointing storm from the arrival times of gate evaluations
/// and raises the gate's confidence threshold in response, so a cross-talk
/// burst is absorbed instead of flooding the panel with one nudge candidate
/// per spurious endpoint.
#[derive(Debug, Clone)]
pub struct StormGuard {
    window: Duration,
    burst_threshold: usize,
    base_threshold: f32,
    max_threshold: f32,
    raise_step: f32,
    current_threshold: f32,
    arrivals: VecDeque<Duration>,
}

impl StormGuard {
    /// Creates a guard that treats `burst_threshold` or more evaluations
    /// arriving within `window` of each other as a storm, raising the gate
    /// threshold from `base_threshold` by `raise_step` per absorbed
    /// evaluation, capped at `max_threshold`.
    ///
    /// `burst_threshold` of `0` has nothing to count up to, so it is
    /// treated as `1` — a single arrival could not otherwise ever be
    /// "clear".
    pub fn new(
        window: Duration,
        burst_threshold: usize,
        base_threshold: f32,
        max_threshold: f32,
        raise_step: f32,
    ) -> Self {
        Self {
            window,
            burst_threshold: burst_threshold.max(1),
            base_threshold,
            max_threshold,
            raise_step,
            current_threshold: base_threshold,
            arrivals: VecDeque::new(),
        }
    }

    /// Records one evaluation arriving at `at` — a monotonic offset into
    /// the meeting, matching how the rest of the capture pipeline stamps
    /// timing (see `capture::vad`) rather than wall-clock time, so this
    /// stays pure and replayable — and returns whether it should be gated
    /// normally or has been absorbed into an ongoing storm.
    pub fn record(&mut self, at: Duration) -> StormOutcome {
        while let Some(&oldest) = self.arrivals.front() {
            if at.saturating_sub(oldest) > self.window {
                self.arrivals.pop_front();
            } else {
                break;
            }
        }

        if self.arrivals.is_empty() {
            // A full window of quiet since the last arrival: any storm has
            // fully subsided, so the threshold relaxes back to baseline
            // rather than staying elevated for the rest of the meeting.
            self.current_threshold = self.base_threshold;
        }

        self.arrivals.push_back(at);

        if self.arrivals.len() >= self.burst_threshold {
            self.current_threshold = (self.current_threshold + self.raise_step).min(self.max_threshold);
            StormOutcome::StormAbsorbed {
                burst_len: self.arrivals.len(),
                raised_threshold: self.current_threshold,
            }
        } else {
            StormOutcome::Clear {
                threshold: self.current_threshold,
            }
        }
    }

    /// The confidence threshold the gate should be using right now — the
    /// base threshold, or an elevated one if a storm is in progress or has
    /// only just subsided.
    pub fn current_threshold(&self) -> f32 {
        self.current_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const WINDOW: Duration = Duration::from_millis(500);

    fn ms(n: u64) -> Duration {
        Duration::from_millis(n)
    }

    #[test]
    fn arrivals_below_the_burst_threshold_stay_clear_at_the_base_threshold() {
        let mut guard = StormGuard::new(WINDOW, 4, 0.6, 0.9, 0.1);

        assert_eq!(guard.record(ms(0)), StormOutcome::Clear { threshold: 0.6 });
        assert_eq!(
            guard.record(ms(100)),
            StormOutcome::Clear { threshold: 0.6 }
        );
        assert_eq!(
            guard.record(ms(200)),
            StormOutcome::Clear { threshold: 0.6 }
        );
    }

    #[test]
    fn a_cross_talk_burst_within_the_window_is_absorbed_rather_than_gated() {
        // 0.5 and 0.25 are exactly representable in f32, so the raised
        // threshold below is exact arithmetic rather than an approximation
        // that would need an epsilon comparison.
        let mut guard = StormGuard::new(WINDOW, 4, 0.5, 0.9, 0.25);

        guard.record(ms(0));
        guard.record(ms(100));
        guard.record(ms(200));
        // The 4th arrival within the window crosses the burst threshold.
        assert_eq!(
            guard.record(ms(300)),
            StormOutcome::StormAbsorbed {
                burst_len: 4,
                raised_threshold: 0.75,
            }
        );
    }

    #[test]
    fn the_storm_keeps_raising_the_threshold_while_it_continues_but_caps_at_max() {
        let mut guard = StormGuard::new(WINDOW, 2, 0.25, 0.9, 0.25);

        guard.record(ms(0));
        assert_eq!(
            guard.record(ms(10)),
            StormOutcome::StormAbsorbed {
                burst_len: 2,
                raised_threshold: 0.5,
            }
        );
        assert_eq!(
            guard.record(ms(20)),
            StormOutcome::StormAbsorbed {
                burst_len: 3,
                raised_threshold: 0.75,
            }
        );
        // Would be 1.0 uncapped; max_threshold holds it at 0.9.
        assert_eq!(
            guard.record(ms(30)),
            StormOutcome::StormAbsorbed {
                burst_len: 4,
                raised_threshold: 0.9,
            }
        );
    }

    #[test]
    fn arrivals_outside_the_window_do_not_count_toward_the_burst() {
        let mut guard = StormGuard::new(WINDOW, 3, 0.6, 0.9, 0.1);

        guard.record(ms(0));
        guard.record(ms(100));
        // Arrives 600ms later, well outside the 500ms window, so the first
        // two arrivals have already aged out — this is not a 3rd arrival
        // within the window, it is the 1st of a fresh one.
        assert_eq!(
            guard.record(ms(700)),
            StormOutcome::Clear { threshold: 0.6 }
        );
    }

    #[test]
    fn the_threshold_relaxes_back_to_base_once_the_storm_fully_subsides() {
        let mut guard = StormGuard::new(WINDOW, 2, 0.5, 0.9, 0.25);

        guard.record(ms(0));
        assert_eq!(
            guard.record(ms(10)),
            StormOutcome::StormAbsorbed {
                burst_len: 2,
                raised_threshold: 0.75,
            }
        );

        // A full window of quiet: the storm is over.
        assert_eq!(
            guard.record(ms(10) + WINDOW + ms(1)),
            StormOutcome::Clear { threshold: 0.5 }
        );
    }

    #[test]
    fn a_burst_threshold_of_zero_is_treated_as_one_so_the_first_arrival_can_storm() {
        let mut guard = StormGuard::new(WINDOW, 0, 0.5, 0.9, 0.25);

        assert_eq!(
            guard.record(ms(0)),
            StormOutcome::StormAbsorbed {
                burst_len: 1,
                raised_threshold: 0.75,
            }
        );
    }

    #[test]
    fn current_threshold_reflects_the_guards_state_without_recording() {
        let mut guard = StormGuard::new(WINDOW, 2, 0.5, 0.9, 0.25);
        assert_eq!(guard.current_threshold(), 0.5);

        guard.record(ms(0));
        guard.record(ms(10));
        assert_eq!(guard.current_threshold(), 0.75);
    }
}
