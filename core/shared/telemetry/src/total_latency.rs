//! End-to-end speech-end-to-nudge-visible latency (PRD NFR-1).
//!
//! [`crate::StageTimers`] answers "which stage is slow" by keeping one
//! histogram per stage. That's necessary but not sufficient: NFR-1's actual
//! requirement is stated in terms of the *whole* path, from the moment a
//! participant stops speaking to the moment a nudge is visible in the UI --
//! "against the 2.0 second p50 target". Summing stage medians doesn't
//! answer that, because a slow tail in one stage can overlap with a fast
//! run in another; only a histogram fed the actual end-to-end sample
//! answers it. [`TotalLatencyTracker`] is that dedicated histogram, plus
//! the target comparison so callers don't each re-implement "is p50 within
//! budget" against a hardcoded number.
//!
//! NFR-1 also sets a p95 bar (≤3.5s), and that bar is judged against its
//! own target rather than folded into `meets_p50_target`: "mean-silence
//! parameters do not govern p95 -- the forced-end ceiling does" (the ASR
//! provider's `max_turn_silence`, tuned independently from the p50-governing
//! `min_turn_silence`). Because a different knob governs each end of the
//! distribution, a run can meet one bar and miss the other, so
//! [`TotalLatencySnapshot`] reports `meets_p50_target` and
//! `meets_p95_target` as two independent booleans rather than a single
//! blended verdict.
use std::time::{Duration, Instant};

use crate::histogram::{LatencyHistogram, Snapshot};

/// PRD NFR-1's p50 budget for the full speech-end-to-nudge-visible path.
pub const P50_TARGET_MS: f64 = 2000.0;

/// PRD NFR-1's p95 budget for the full speech-end-to-nudge-visible path.
/// Governed by the ASR provider's forced turn-end ceiling
/// (`max_turn_silence`), not by the mean-silence parameter that governs
/// p50 -- so this target is checked independently of `P50_TARGET_MS`.
pub const P95_TARGET_MS: f64 = 3500.0;

/// Tracks the full speech-end-to-nudge-visible latency as a single
/// end-to-end histogram, separate from any individual stage.
#[derive(Default)]
pub struct TotalLatencyTracker {
    histogram: LatencyHistogram,
}

impl TotalLatencyTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Records one end-to-end sample: the elapsed time from speech-end to
    /// the nudge becoming visible.
    pub fn record(&self, latency: Duration) {
        self.histogram.record(latency);
    }

    /// Starts timing one speech-end-to-nudge-visible span; the elapsed time
    /// is recorded automatically when the returned guard drops.
    pub fn start(&self) -> TotalLatencyGuard<'_> {
        TotalLatencyGuard {
            tracker: self,
            start: Instant::now(),
        }
    }

    /// Reads back the current distribution together with whether p50 and
    /// p95 are each within NFR-1's targets. The two are judged
    /// independently -- a different knob governs each end of the
    /// distribution, so a run can meet one bar and miss the other. An
    /// empty tracker has no data to judge, so both report `false` rather
    /// than vacuously meeting their targets.
    pub fn snapshot(&self) -> TotalLatencySnapshot {
        let snapshot = self.histogram.snapshot();
        TotalLatencySnapshot {
            snapshot,
            meets_p50_target: snapshot.count > 0 && snapshot.p50_ms <= P50_TARGET_MS,
            meets_p95_target: snapshot.count > 0 && snapshot.p95_ms <= P95_TARGET_MS,
        }
    }
}

pub struct TotalLatencyGuard<'a> {
    tracker: &'a TotalLatencyTracker,
    start: Instant,
}

impl Drop for TotalLatencyGuard<'_> {
    fn drop(&mut self) {
        self.tracker.record(self.start.elapsed());
    }
}

/// The end-to-end distribution as of one point in time, plus whether it
/// currently meets NFR-1's p50 and p95 targets. The two flags are
/// independent: p50 is governed by mean-silence tuning and p95 by the
/// forced turn-end ceiling, so one can hold while the other slips.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TotalLatencySnapshot {
    pub snapshot: Snapshot,
    pub meets_p50_target: bool,
    pub meets_p95_target: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_tracker_does_not_vacuously_meet_the_target() {
        let tracker = TotalLatencyTracker::new();
        let snapshot = tracker.snapshot();
        assert_eq!(snapshot.snapshot.count, 0);
        assert!(!snapshot.meets_p50_target);
        assert!(!snapshot.meets_p95_target);
    }

    #[test]
    fn p50_within_budget_meets_the_target() {
        let tracker = TotalLatencyTracker::new();
        for _ in 0..20 {
            tracker.record(Duration::from_millis(1500));
        }
        let snapshot = tracker.snapshot();
        assert!(snapshot.snapshot.p50_ms <= P50_TARGET_MS);
        assert!(snapshot.meets_p50_target);
    }

    #[test]
    fn p50_over_budget_fails_the_target_even_with_some_fast_samples() {
        let tracker = TotalLatencyTracker::new();
        // A minority of fast samples shouldn't hide a median that blows
        // the budget -- NFR-1 is about the experience of the typical
        // participant, not the best case.
        for _ in 0..5 {
            tracker.record(Duration::from_millis(200));
        }
        for _ in 0..20 {
            tracker.record(Duration::from_millis(2600));
        }
        let snapshot = tracker.snapshot();
        assert!(snapshot.snapshot.p50_ms > P50_TARGET_MS);
        assert!(!snapshot.meets_p50_target);
    }

    #[test]
    fn exactly_at_the_target_still_counts_as_meeting_it() {
        let tracker = TotalLatencyTracker::new();
        for _ in 0..10 {
            tracker.record(Duration::from_millis(P50_TARGET_MS as u64));
        }
        let snapshot = tracker.snapshot();
        assert!(snapshot.meets_p50_target);
    }

    #[test]
    fn p95_within_budget_meets_the_target() {
        let tracker = TotalLatencyTracker::new();
        for _ in 0..19 {
            tracker.record(Duration::from_millis(500));
        }
        tracker.record(Duration::from_millis(3000));
        let snapshot = tracker.snapshot();
        assert!(snapshot.snapshot.p95_ms <= P95_TARGET_MS);
        assert!(snapshot.meets_p95_target);
    }

    #[test]
    fn p95_over_budget_fails_the_target() {
        let tracker = TotalLatencyTracker::new();
        // A tail past the forced turn-end ceiling should pull p95 over
        // budget even though the bulk of samples are fast.
        for _ in 0..90 {
            tracker.record(Duration::from_millis(500));
        }
        for _ in 0..10 {
            tracker.record(Duration::from_millis(6000));
        }
        let snapshot = tracker.snapshot();
        assert!(snapshot.snapshot.p95_ms > P95_TARGET_MS);
        assert!(!snapshot.meets_p95_target);
    }

    #[test]
    fn p50_target_missed_but_p95_target_still_met_are_reported_independently() {
        // p50 and p95 are governed by different knobs (mean-silence vs.
        // the forced turn-end ceiling), so a run can blow one budget while
        // still meeting the other -- the two flags must not be collapsed
        // into a single verdict.
        let tracker = TotalLatencyTracker::new();
        for _ in 0..20 {
            tracker.record(Duration::from_millis(2500));
        }
        let snapshot = tracker.snapshot();
        assert!(snapshot.snapshot.p50_ms > P50_TARGET_MS);
        assert!(snapshot.snapshot.p95_ms <= P95_TARGET_MS);
        assert!(!snapshot.meets_p50_target);
        assert!(snapshot.meets_p95_target);
    }

    #[test]
    fn guard_records_elapsed_time_on_drop() {
        let tracker = TotalLatencyTracker::new();
        {
            let _guard = tracker.start();
            std::thread::sleep(Duration::from_millis(5));
        }
        let snapshot = tracker.snapshot();
        assert_eq!(snapshot.snapshot.count, 1);
        assert!(snapshot.snapshot.p50_ms >= 4.0);
    }
}
