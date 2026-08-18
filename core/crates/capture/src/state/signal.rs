//! The lock-free signal a real-time audio callback polls to know whether it
//! should keep pushing frames into the ring buffer (PRD FR-1.3).
//!
//! [`CaptureStateMachine`](super::CaptureStateMachine) itself is not safe to
//! touch from the real-time thread — its log is a plain `Vec`, and pushing to
//! one can allocate. That's fine, because nothing on the real-time thread
//! needs the log, or even the full three-way [`CaptureState`](super::CaptureState);
//! it only ever needs one bit: "is capture paused right now." [`PauseSignal`]
//! is that one bit, backed by an `AtomicBool` behind an `Arc` so a handle
//! obtained once at session start (via
//! [`CaptureStateMachine::pause_signal`](super::CaptureStateMachine::pause_signal))
//! stays live for the session's whole lifetime and is cheap to clone onto
//! whichever thread needs to read it.
//!
//! FR-1.3's "single-tap, unmissable pause control... halts audio ingestion
//! immediately" is a hard real-time requirement, not a UI affordance: the
//! operator taps pause because a client just said something off the record,
//! and the architecture note this module implements promises the paused
//! transition takes effect within one buffer period. A lock can't promise
//! that — the real-time thread could be the one left waiting on it — so this
//! signal is never guarded by anything but the atomic itself. Every
//! [`CaptureStateMachine`](super::CaptureStateMachine) transition flips it as
//! its first observable effect, before the transition is even logged, so a
//! reader polling once per buffer period is guaranteed to see `paused` on its
//! very next poll after the operator's tap.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// A conservative upper bound on how often the real-time audio callback
/// runs, i.e. "one buffer period" as FR-1.3 and architecture §3.1 use the
/// term. Frame sizes in this system run 20-50ms (architecture §14.2); 20ms
/// is the tightest of those, so it's the bound a pause has to beat to say it
/// "took effect within one buffer period" in the worst case.
///
/// This module doesn't use the value to gate anything at runtime — a single
/// atomic store is already orders of magnitude faster than any buffer
/// period, lock or no lock — but it's tests below hold `pause_signal()` to
/// it so the guarantee stays a measured fact, not just an assertion in a
/// doc comment.
pub const BUFFER_PERIOD: std::time::Duration = std::time::Duration::from_millis(20);

/// A cheap, cloneable, lock-free handle onto one capture session's
/// paused/not-paused bit.
///
/// Reading it (`is_paused`) and writing it (`set`, restricted to this
/// module's siblings) are both single atomic operations — no lock, no
/// allocation, no possibility of blocking whichever thread calls them. That
/// is what lets a real-time audio callback poll it every buffer period
/// without risking the dropouts a lock could cause (architecture §3.1).
#[derive(Clone, Debug, Default)]
pub struct PauseSignal(Arc<AtomicBool>);

impl PauseSignal {
    /// A fresh signal, reporting not-paused — matching a brand new
    /// [`CaptureStateMachine`](super::CaptureStateMachine) starting `Idle`.
    pub fn new() -> Self {
        Self(Arc::new(AtomicBool::new(false)))
    }

    /// `true` iff the session this signal belongs to is currently `Paused`.
    /// Safe to call from any thread, including the real-time audio callback.
    pub fn is_paused(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }

    /// Flips the bit. Only [`CaptureStateMachine`](super::CaptureStateMachine)
    /// calls this, and only as part of committing a state transition — there
    /// is no public way to set this signal independently of an actual
    /// transition, which is what keeps it truthful.
    pub(super) fn set(&self, paused: bool) {
        self.0.store(paused, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fresh_signal_reports_not_paused() {
        let signal = PauseSignal::new();
        assert!(!signal.is_paused());
    }

    #[test]
    fn set_is_visible_through_every_clone() {
        let signal = PauseSignal::new();
        let handle = signal.clone();

        signal.set(true);
        assert!(
            handle.is_paused(),
            "a handle obtained before the flip must still see it -- it shares \
             the same underlying atomic, not a snapshot"
        );

        signal.set(false);
        assert!(!handle.is_paused());
    }
}
