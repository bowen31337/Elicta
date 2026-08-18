use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

/// Growth factor between successive bucket bounds. Small enough that
/// percentile interpolation stays reasonably tight (~40% bucket width)
/// while still covering the full latency range in a few dozen buckets.
const BUCKET_GROWTH: f64 = 1.4;

/// Largest finite bucket bound, in milliseconds. Comfortably above the
/// slowest end-to-end budget in the pipeline (NFR-1's 3.5s p95 for
/// speech-end to nudge visible), so a healthy system never spills into the
/// overflow bucket.
const MAX_BOUND_MS: f64 = 20_000.0;

fn bucket_bounds() -> Vec<f64> {
    let mut bounds = Vec::new();
    let mut bound = 1.0;
    while bound < MAX_BOUND_MS {
        bounds.push(bound);
        bound *= BUCKET_GROWTH;
    }
    bounds.push(MAX_BOUND_MS);
    bounds
}

/// A per-stage latency distribution, recorded as bucketed counts rather
/// than a running average. The architecture note this type exists to
/// satisfy is explicit: "Instrument at every arrow. Ship the histogram,
/// not an average — p95 is what the operator experiences as 'it's laggy'."
pub struct LatencyHistogram {
    bounds: Vec<f64>,
    /// `counts[i]` holds samples with `bounds[i-1] < x <= bounds[i]`
    /// (`bounds[-1]` treated as 0.0). The last slot is the overflow bucket
    /// for samples above the largest bound.
    counts: Vec<AtomicU64>,
}

impl LatencyHistogram {
    pub fn new() -> Self {
        let bounds = bucket_bounds();
        let mut counts = Vec::with_capacity(bounds.len() + 1);
        counts.resize_with(bounds.len() + 1, || AtomicU64::new(0));
        Self { bounds, counts }
    }

    /// Records one latency sample. Safe to call concurrently from multiple
    /// tasks recording the same stage.
    pub fn record(&self, latency: Duration) {
        let ms = latency.as_secs_f64() * 1000.0;
        let index = self
            .bounds
            .iter()
            .position(|&bound| ms <= bound)
            .unwrap_or(self.bounds.len());
        self.counts[index].fetch_add(1, Ordering::Relaxed);
    }

    /// Reads back the current count, p50, and p95 as of this call.
    pub fn snapshot(&self) -> Snapshot {
        let counts: Vec<u64> = self
            .counts
            .iter()
            .map(|count| count.load(Ordering::Relaxed))
            .collect();
        let total: u64 = counts.iter().sum();
        Snapshot {
            count: total,
            p50_ms: self.percentile(&counts, total, 0.50),
            p95_ms: self.percentile(&counts, total, 0.95),
        }
    }

    /// Estimates the given percentile from bucketed counts by nearest
    /// rank, linearly interpolating within whichever bucket contains that
    /// rank — the same approach Prometheus's `histogram_quantile` uses.
    fn percentile(&self, counts: &[u64], total: u64, p: f64) -> f64 {
        if total == 0 {
            return 0.0;
        }
        let rank = (p * total as f64).ceil();
        let mut cumulative = 0u64;
        let mut lower_bound = 0.0;
        for (i, &count) in counts.iter().enumerate() {
            let upper_bound = self.bounds.get(i).copied().unwrap_or(f64::INFINITY);
            if cumulative as f64 + count as f64 >= rank {
                if count == 0 || upper_bound.is_infinite() {
                    // Can't interpolate into an empty or unbounded bucket —
                    // the lower edge is the best conservative estimate.
                    return lower_bound;
                }
                let fraction = (rank - cumulative as f64) / count as f64;
                return lower_bound + fraction * (upper_bound - lower_bound);
            }
            cumulative += count;
            lower_bound = upper_bound;
        }
        lower_bound
    }
}

impl Default for LatencyHistogram {
    fn default() -> Self {
        Self::new()
    }
}

/// A stage's latency distribution as of one point in time: how many
/// samples have been recorded, and the p50/p95 estimated from them.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Snapshot {
    pub count: u64,
    pub p50_ms: f64,
    pub p95_ms: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_histogram_reports_zero() {
        let histogram = LatencyHistogram::new();
        let snapshot = histogram.snapshot();
        assert_eq!(snapshot.count, 0);
        assert_eq!(snapshot.p50_ms, 0.0);
        assert_eq!(snapshot.p95_ms, 0.0);
    }

    #[test]
    fn p50_and_p95_diverge_under_a_skewed_distribution() {
        let histogram = LatencyHistogram::new();
        // Ninety fast calls plus ten slow outliers should put p50 near the
        // fast cluster and p95 near the slow one -- an average would blend
        // them into a number that describes neither experience.
        for _ in 0..90 {
            histogram.record(Duration::from_millis(50));
        }
        for _ in 0..10 {
            histogram.record(Duration::from_millis(3000));
        }

        let snapshot = histogram.snapshot();
        assert_eq!(snapshot.count, 100);
        assert!(
            snapshot.p50_ms < 200.0,
            "p50 {} should stay near the fast cluster",
            snapshot.p50_ms
        );
        assert!(
            snapshot.p95_ms > 1000.0,
            "p95 {} should reflect the slow outliers",
            snapshot.p95_ms
        );
        assert!(snapshot.p50_ms < snapshot.p95_ms);
    }

    #[test]
    fn percentile_scales_with_recorded_magnitude() {
        let low = LatencyHistogram::new();
        let high = LatencyHistogram::new();
        for _ in 0..20 {
            low.record(Duration::from_millis(20));
            high.record(Duration::from_millis(2000));
        }
        assert!(low.snapshot().p50_ms < high.snapshot().p50_ms);
    }

    #[test]
    fn samples_above_the_largest_bucket_still_land_in_the_upper_percentile() {
        let histogram = LatencyHistogram::new();
        for _ in 0..100 {
            histogram.record(Duration::from_secs(60));
        }
        let snapshot = histogram.snapshot();
        assert_eq!(snapshot.count, 100);
        assert!(snapshot.p95_ms >= MAX_BOUND_MS * 0.9);
    }
}
