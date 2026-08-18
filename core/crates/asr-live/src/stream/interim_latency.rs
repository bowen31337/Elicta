//! The FR-2.1 latency budget: "System emits an InterimHypothesis event
//! carrying stream_id, text, and started_at within 400 milliseconds of
//! speech onset." Every [`InterimHypothesis`] already carries `started_at`
//! — the speech onset it hypothesises text for (`backend::event`,
//! `fake.rs`'s scripted interims) — so the field this FR asks for already
//! exists; what this module adds is the check that a hypothesis actually
//! reached a consumer before that clock ran out, not just that the field is
//! populated correctly once it arrives.
//!
//! Distinct from [`super::FirstPartialDelay`] (PRD FR-5.9): that module
//! decides how soon this system *asks the engine* to emit a first partial.
//! This one measures whether whatever partial the engine actually returned
//! — first or a later revision — reached a consumer within the budget
//! speech onset itself imposes on any interim, independent of what delay
//! was requested on the handshake.

use std::time::Duration;

use crate::backend::{InterimHypothesis, StreamId};

/// The FR-2.1 budget: every [`InterimHypothesis`] must reach a consumer
/// within 400ms of the speech onset it carries in `started_at`.
pub const INTERIM_LATENCY_BUDGET: Duration = Duration::from_millis(400);

/// An [`InterimHypothesis`] that reached a consumer later than
/// [`INTERIM_LATENCY_BUDGET`] after the speech onset it carries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InterimLatencyExceeded {
    pub stream_id: StreamId,
    pub started_at: Duration,
    pub observed_at: Duration,
    pub over_by: Duration,
}

/// Checks one [`InterimHypothesis`] against the FR-2.1 budget. `observed_at`
/// is when a consumer actually saw it, measured on the same stream-relative
/// clock as `started_at` — this never reads a real clock itself, mirroring
/// `turn_silence::TuningReport::from_samples` taking a batch of samples by
/// value rather than instrumenting one, since a caller (or a test) is
/// always the one who actually knows when an event was observed.
///
/// Returns the observed latency on success so a caller that only wants the
/// number, not a pass/fail, doesn't have to recompute it.
pub fn check_interim_latency(
    interim: &InterimHypothesis,
    observed_at: Duration,
) -> Result<Duration, InterimLatencyExceeded> {
    let latency = observed_at.saturating_sub(interim.started_at);
    if latency <= INTERIM_LATENCY_BUDGET {
        Ok(latency)
    } else {
        Err(InterimLatencyExceeded {
            stream_id: interim.stream_id.clone(),
            started_at: interim.started_at,
            observed_at,
            over_by: latency - INTERIM_LATENCY_BUDGET,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn interim(stream_id: &str, started_at_ms: u64) -> InterimHypothesis {
        InterimHypothesis {
            stream_id: stream_id.to_string(),
            text: "we need to".to_string(),
            started_at: Duration::from_millis(started_at_ms),
        }
    }

    #[test]
    fn an_interim_observed_well_within_budget_reports_its_latency() {
        let latency = check_interim_latency(&interim("stream-1", 0), Duration::from_millis(150))
            .expect("150ms is within the 400ms FR-2.1 budget");
        assert_eq!(latency, Duration::from_millis(150));
    }

    #[test]
    fn an_interim_observed_exactly_at_the_budget_still_counts_as_on_time() {
        let latency = check_interim_latency(&interim("stream-1", 0), Duration::from_millis(400))
            .expect("exactly 400ms should still satisfy the budget, not just less than it");
        assert_eq!(latency, INTERIM_LATENCY_BUDGET);
    }

    #[test]
    fn an_interim_observed_one_millisecond_past_the_budget_is_rejected() {
        let error = check_interim_latency(&interim("stream-1", 0), Duration::from_millis(401))
            .expect_err("401ms exceeds the documented 400ms FR-2.1 budget");
        assert_eq!(
            error,
            InterimLatencyExceeded {
                stream_id: "stream-1".to_string(),
                started_at: Duration::ZERO,
                observed_at: Duration::from_millis(401),
                over_by: Duration::from_millis(1),
            }
        );
    }

    #[test]
    fn the_budget_measures_from_speech_onset_not_from_the_streams_start() {
        // started_at is 900ms into the stream (the second utterance in
        // `fake.rs`'s premature-endpoint script); the budget still runs
        // from that onset, not from the stream's own t=0.
        let on_time = check_interim_latency(&interim("stream-1", 900), Duration::from_millis(1290))
            .expect("390ms after this utterance's own onset is within budget");
        assert_eq!(on_time, Duration::from_millis(390));

        let late = check_interim_latency(&interim("stream-1", 900), Duration::from_millis(1301))
            .expect_err("401ms after this utterance's own onset exceeds the budget");
        assert_eq!(late.over_by, Duration::from_millis(1));
    }

    #[test]
    fn an_observation_timestamp_before_onset_never_underflows() {
        // Guards against a caller passing a stale or out-of-order
        // `observed_at`; `Duration` cannot go negative, so this must
        // saturate to zero latency rather than panic.
        let latency = check_interim_latency(&interim("stream-1", 900), Duration::from_millis(500))
            .expect("a non-negative latency of zero is always within budget");
        assert_eq!(latency, Duration::ZERO);
    }
}
