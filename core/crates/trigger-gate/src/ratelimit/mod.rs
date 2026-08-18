//! Gate self-regulation bookkeeping (PRD FR-5.7, architecture §3.5): "the
//! gate ... maintains a rolling pass-rate counter" across the meeting.
//!
//! `parse` decides whether one candidate span fires or is suppressed; this
//! module tracks, across the rolling window of recent evaluations, what
//! fraction of them fired — the number FR-5.7's ~10%-of-utterances budget
//! is checked against. The two are independent: `parse` never needs to know
//! the running pass rate to gate a single span, and this module never needs
//! to know why a span fired or was suppressed, only that it did or didn't.
//!
//! [`PassRateCounter`] only counts; it does not itself decide anything from
//! the number it produces. [`regulation::ThresholdRegulator`] is the
//! consumer that closes the loop: raising the gate's own thresholds in
//! response to a high pass rate — the self-regulation half of architecture
//! §3.5's "and raises its own thresholds if pass rate exceeds ~10%"
//! (PRD FR-5.7) — by consuming [`PassRateCounter::record`]'s return value.
//!
//! [`storm`] is the sibling concern for the burstier failure mode in the
//! architecture's risk table: an endpointing storm during cross-talk, where
//! a flood of evaluations arrives faster than the rolling pass rate could
//! ever react to. It watches evaluation arrival times directly rather than
//! consuming [`PassRateCounter`]'s output.

pub mod pass_rate;
pub mod regulation;
pub mod storm;

pub use pass_rate::PassRateCounter;
pub use regulation::{RegulationOutcome, ThresholdRegulator};
pub use storm::{StormGuard, StormOutcome};
