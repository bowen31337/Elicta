//! Gate self-regulation bookkeeping (PRD FR-5.7, architecture §3.5): "the
//! gate ... maintains a rolling pass-rate counter" across the meeting.
//!
//! `parse` decides whether one candidate span fires or is suppressed; this
//! module tracks, across the rolling window of recent evaluations, what
//! fraction of them fired — the number FR-5.7's ~10%-of-utterances budget
//! is checked against. The two are independent: `parse` never needs to know
//! the running pass rate to gate a single span, and this module never needs
//! to know why a span fired or was suppressed, only that it did or didn't.

pub mod pass_rate;

pub use pass_rate::PassRateCounter;
