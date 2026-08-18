//! Slow lane orchestrator (architecture §3.8, §6, §14.3; PRD FR-5.10):
//! fires a slow-lane pass on a 60-second tick without ever blocking the
//! deterministic fast lane. Architecture §6's concurrency table puts the
//! two on separate footing on purpose — the trigger task must complete
//! in under 100ms, while the slow lane task is merely "cancellable;
//! failure is non-fatal" — so this crate runs its tick source
//! ([`ticker::SlowLaneTicker`]) on its own dedicated thread that only
//! ever sends events outward, never something the fast lane calls into
//! or waits on.
//!
//! [`orchestrator::SlowLaneOrchestrator`] holds the other load-bearing
//! invariant architecture §14.3 names for this component: never let two
//! ticks be in flight at once, since a hung pass plus the next scheduled
//! tick would otherwise pay full (uncached) price on both requests.
//!
//! Assembling the actual partitioned prompt, calling the Messages API,
//! and writing coverage updates/candidates back into the bank (§3.8) are
//! separate features that consume the events and decisions this crate
//! produces — this crate owns the tick and the overlap invariant only.

pub mod orchestrator;
pub mod replay;
pub mod ticker;

pub use orchestrator::{SlowLaneOrchestrator, TickDecision};
pub use replay::ReplayRun;
pub use ticker::{SlowLaneTicker, TickEvent, DEFAULT_TICK_INTERVAL};

/// End-to-end proof that the two halves of this crate compose into what
/// PRD FR-5.10 actually asks for: a slow lane that fires a pass on every
/// tick of its interval, run entirely off a background thread the caller
/// never has to poll or block on.
#[cfg(test)]
mod orchestrator_ticks_end_to_end {
    use super::*;
    use std::time::Duration;

    #[test]
    fn the_orchestrator_fires_a_pass_decision_on_every_tick_without_the_caller_blocking() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();

        // Spawning and driving the loop below never calls anything that
        // sleeps for the interval itself — every tick arrives via the
        // channel on its own schedule while this thread just drains it,
        // which is the shape "never blocks the deterministic path" takes
        // in practice: nothing here can stall a caller waiting on it.
        let mut decisions = Vec::new();
        for _ in 0..4 {
            let event = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
            let decision = orchestrator.on_tick(event);
            orchestrator.mark_complete(); // pass finishes well inside the interval
            decisions.push(decision);
        }

        let sequences: Vec<u64> = decisions
            .iter()
            .map(|decision| match decision {
                TickDecision::Start(event) => event.sequence,
                TickDecision::CancelInFlightAndStart(event) => event.sequence,
            })
            .collect();
        assert_eq!(sequences, vec![0, 1, 2, 3], "a pass fires for every tick, in order");

        assert!(
            decisions.iter().all(|decision| matches!(decision, TickDecision::Start(_))),
            "a pass that completes before the next tick must never be treated as an overlap"
        );

        ticker.stop();
    }

    /// A hung pass (never `mark_complete`d) must not stop the tick source
    /// itself from firing on schedule — the orchestrator's job is to
    /// notice the overlap and say so, not for the ticker to slow down and
    /// wait for whoever is slow to consume it.
    #[test]
    fn a_hung_pass_still_lets_the_next_tick_arrive_on_schedule_and_is_reported_as_an_overlap() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();

        let first = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(orchestrator.on_tick(first), TickDecision::Start(first));
        // Deliberately never call mark_complete() for this tick.

        let second = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(
            orchestrator.on_tick(second),
            TickDecision::CancelInFlightAndStart(second),
            "the next tick still arrives on schedule and is flagged to cancel-and-replace"
        );

        ticker.stop();
    }
}
