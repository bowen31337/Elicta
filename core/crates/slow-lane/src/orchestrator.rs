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

/// The record that a specific in-flight tick got cancelled, emitted per
/// §14.3's "cancel and replace; never overlap" rule. Naming which tick was
/// cancelled — not just that *some* pass got interrupted — is what lets a
/// caller log or alert on the overlap instead of only knowing a new pass
/// started.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickCancelled {
    /// The tick whose still-running pass got cancelled.
    pub cancelled: TickEvent,
    /// The tick that superseded it and starts fresh instead.
    pub superseded_by: TickEvent,
}

/// What a caller should do with an incoming [`TickEvent`], given whether a
/// pass from a previous tick is still running.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TickDecision {
    /// No pass is in flight; start one for this tick.
    Start(TickEvent),
    /// A previous tick's pass is still running. Per §14.3, the caller
    /// must cancel it and start fresh against this tick instead of
    /// letting both run — never queue, never run concurrently. Carries a
    /// [`TickCancelled`] naming which tick got cancelled, not just the one
    /// replacing it.
    CancelInFlightAndStart(TickCancelled),
}

impl TickDecision {
    /// The tick to start a pass for, regardless of which variant this is.
    pub fn tick(&self) -> TickEvent {
        match self {
            TickDecision::Start(event) => *event,
            TickDecision::CancelInFlightAndStart(cancelled) => cancelled.superseded_by,
        }
    }
}

/// Tracks whether a slow-lane pass is currently in flight, so at most one
/// ever is. Holds no I/O of its own — a caller drives it with the tick
/// events it receives from [`crate::ticker::SlowLaneTicker`] and reports
/// back via [`SlowLaneOrchestrator::mark_complete`] when a pass (started
/// or cancelled) has actually stopped running.
#[derive(Debug, Default)]
pub struct SlowLaneOrchestrator {
    in_flight: Option<TickEvent>,
}

impl SlowLaneOrchestrator {
    pub fn new() -> Self {
        Self { in_flight: None }
    }

    /// Decides what to do with `event`. A slow-lane failure must never be
    /// fatal (architecture §3.8, NFR-4.1) and this method never panics or
    /// returns an error for any input — the worst outcome it can produce
    /// is asking the caller to cancel and restart.
    pub fn on_tick(&mut self, event: TickEvent) -> TickDecision {
        let decision = match self.in_flight {
            Some(previous) => {
                TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: previous, superseded_by: event })
            }
            None => TickDecision::Start(event),
        };
        self.in_flight = Some(event);
        decision
    }

    /// Reports that whatever pass was in flight (started or cancelled) has
    /// now actually stopped running, so the next tick may start cleanly.
    pub fn mark_complete(&mut self) {
        self.in_flight = None;
    }

    /// Whether a pass is currently believed to be in flight.
    pub fn is_in_flight(&self) -> bool {
        self.in_flight.is_some()
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
        let first = event(0);
        orchestrator.on_tick(first);

        let second = event(1);
        assert_eq!(
            orchestrator.on_tick(second),
            TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: first, superseded_by: second }),
            "two ticks must never both be treated as started"
        );
    }

    #[test]
    fn a_superseded_tick_emits_a_cancellation_event_naming_which_tick_was_cancelled() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        let first = event(0);
        orchestrator.on_tick(first);

        let second = event(1);
        let decision = orchestrator.on_tick(second);

        let TickDecision::CancelInFlightAndStart(cancelled) = decision else {
            panic!("expected a cancel-and-replace decision, got {decision:?}");
        };
        assert_eq!(
            cancelled.cancelled, first,
            "the cancellation event must name the tick that got cancelled, not just the one replacing it"
        );
        assert_eq!(cancelled.superseded_by, second);
    }

    #[test]
    fn a_chain_of_uncompleted_ticks_each_cancels_the_immediately_previous_one() {
        let mut orchestrator = SlowLaneOrchestrator::new();
        let first = event(0);
        orchestrator.on_tick(first);

        let second = event(1);
        assert_eq!(
            orchestrator.on_tick(second),
            TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: first, superseded_by: second })
        );

        let third = event(2);
        assert_eq!(
            orchestrator.on_tick(third),
            TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: second, superseded_by: third }),
            "each cancellation must name the tick actually in flight, not the original first tick"
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
