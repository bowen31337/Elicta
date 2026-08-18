//! The overlap invariant (architecture §3.8, §14.3): "never allow two
//! ticks in flight... cancel and replace; never overlap." A cache entry
//! only becomes readable once a request starts streaming, so two
//! concurrent requests against the same prefix both pay full price —
//! exactly what a hung pass plus the next scheduled tick would otherwise
//! produce. [`SlowLaneOrchestrator`] is the pure decision point that
//! keeps that from happening; it holds no network handle and makes no
//! call itself, since which pass implementation to cancel is up to
//! whichever feature wires a real Messages API call to [`crate::ticker`]'s
//! events.

use crate::ticker::TickEvent;

/// What a caller should do with an incoming [`TickEvent`], given whether a
/// pass from a previous tick is still running.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TickDecision {
    /// No pass is in flight; start one for this tick.
    Start(TickEvent),
    /// A previous tick's pass is still running. Per §14.3, the caller
    /// must cancel it and start fresh against this tick instead of
    /// letting both run — never queue, never run concurrently.
    CancelInFlightAndStart(TickEvent),
}

/// Tracks whether a slow-lane pass is currently in flight, so at most one
/// ever is. Holds no I/O of its own — a caller drives it with the tick
/// events it receives from [`crate::ticker::SlowLaneTicker`] and reports
/// back via [`SlowLaneOrchestrator::mark_complete`] when a pass (started
/// or cancelled) has actually stopped running.
#[derive(Debug, Default)]
pub struct SlowLaneOrchestrator {
    in_flight: bool,
}

impl SlowLaneOrchestrator {
    pub fn new() -> Self {
        Self { in_flight: false }
    }

    /// Decides what to do with `event`. A slow-lane failure must never be
    /// fatal (architecture §3.8, NFR-4.1) and this method never panics or
    /// returns an error for any input — the worst outcome it can produce
    /// is asking the caller to cancel and restart.
    pub fn on_tick(&mut self, event: TickEvent) -> TickDecision {
        let decision = if self.in_flight {
            TickDecision::CancelInFlightAndStart(event)
        } else {
            TickDecision::Start(event)
        };
        self.in_flight = true;
        decision
    }

    /// Reports that whatever pass was in flight (started or cancelled) has
    /// now actually stopped running, so the next tick may start cleanly.
    pub fn mark_complete(&mut self) {
        self.in_flight = false;
    }

    /// Whether a pass is currently believed to be in flight.
    pub fn is_in_flight(&self) -> bool {
        self.in_flight
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    fn event(sequence: u64) -> TickEvent {
        TickEvent { sequence, fired_at: Instant::now() }
    }

    #[test]
    fn a_tick_with_nothing_in_flight_starts() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        let first = event(0);
        assert_eq!(orchestrator.on_tick(first), TickDecision::Start(first));
    }

    #[test]
    fn a_second_tick_while_the_first_is_still_in_flight_cancels_and_replaces_rather_than_overlapping() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        orchestrator.on_tick(event(0));

        let second = event(1);
        assert_eq!(
            orchestrator.on_tick(second),
            TickDecision::CancelInFlightAndStart(second),
            "two ticks must never both be treated as started"
        );
    }

    #[test]
    fn a_tick_after_the_previous_pass_completes_starts_cleanly_again() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        orchestrator.on_tick(event(0));
        orchestrator.mark_complete();

        let second = event(1);
        assert_eq!(orchestrator.on_tick(second), TickDecision::Start(second));
    }

    #[test]
    fn is_in_flight_reflects_start_and_completion() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        assert!(!orchestrator.is_in_flight());

        orchestrator.on_tick(event(0));
        assert!(orchestrator.is_in_flight());

        orchestrator.mark_complete();
        assert!(!orchestrator.is_in_flight());
    }

    #[test]
    fn repeated_overlapping_ticks_never_drop_the_in_flight_flag() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        for sequence in 0..5 {
            orchestrator.on_tick(event(sequence));
            assert!(orchestrator.is_in_flight());
        }
    }
}
