//! Performance instrumentation: per-pipeline-stage latency, and slow-lane
//! cache-prefix health.
//!
//! Architecture note this crate exists to satisfy: "Instrument at every
//! arrow. Ship the histogram, not an average — p95 is what the operator
//! experiences as 'it's laggy'." Every stage on the speech-end-to-nudge
//! path (and elsewhere) records its latency into a [`LatencyHistogram`] via
//! [`StageTimers`], and p50/p95 are always read back together rather than
//! collapsed into a single mean.
//!
//! [`CachePrefixMonitor`] covers the other documented failure mode (§14.3):
//! a slow-lane cache prefix that stops caching doesn't error, it just goes
//! quiet — `cache_read_input_tokens` silently drops to zero. Recording
//! each tick's usage turns that silence into a metric.
//!
//! [`TotalLatencyTracker`] is the NFR-1 metric itself: the full
//! speech-end-to-nudge-visible span, recorded as its own end-to-end
//! histogram and compared against the 2.0s p50 target *and* the 3.5s p95
//! target rather than left for callers to infer from the per-stage
//! breakdown. The two targets are reported separately, because a different
//! knob governs each: mean-silence tuning drives p50, while the forced
//! turn-end ceiling drives p95.

mod cache_health;
mod histogram;
mod registry;
mod total_latency;

pub use cache_health::{CacheHealthSnapshot, CachePrefixMonitor, CacheTickUsage};
pub use histogram::{LatencyHistogram, Snapshot};
pub use registry::{StageTimerGuard, StageTimers};
pub use total_latency::{
    TotalLatencyGuard, TotalLatencySnapshot, TotalLatencyTracker, P50_TARGET_MS, P95_TARGET_MS,
};
