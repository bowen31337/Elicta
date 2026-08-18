//! Per-pipeline-stage latency instrumentation.
//!
//! Architecture note this crate exists to satisfy: "Instrument at every
//! arrow. Ship the histogram, not an average — p95 is what the operator
//! experiences as 'it's laggy'." Every stage on the speech-end-to-nudge
//! path (and elsewhere) records its latency into a [`LatencyHistogram`] via
//! [`StageTimers`], and p50/p95 are always read back together rather than
//! collapsed into a single mean.

mod histogram;
mod registry;

pub use histogram::{LatencyHistogram, Snapshot};
pub use registry::{StageTimerGuard, StageTimers};
