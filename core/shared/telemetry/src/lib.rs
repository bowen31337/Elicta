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

mod cache_health;
mod histogram;
mod registry;

pub use cache_health::{CacheHealthSnapshot, CachePrefixMonitor, CacheTickUsage};
pub use histogram::{LatencyHistogram, Snapshot};
pub use registry::{StageTimerGuard, StageTimers};
