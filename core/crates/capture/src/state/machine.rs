//! The capture session's own idle/capturing/paused state machine.
//!
//! A session is always in exactly one of three states, and moves between
//! them only along the edges an operator action or the record pipeline can
//! actually trigger: `start` (Idle -> Capturing), `pause` (Capturing ->
//! Paused), `resume` (Paused -> Capturing), and `stop` (Capturing or Paused
//! -> Idle). Every other pair — e.g. pausing while already idle, or starting
//! while already capturing — is rejected rather than silently coerced,
//! because a caller that thinks it just started capture when the session was
//! already capturing is a caller with a wrong mental model of what's
//! recording right now.
//!
//! [`CaptureStateMachine::log`] is the guarantee this module exists to make:
//! there is no way to change `state()` without a [`CaptureTransitionEvent`]
//! being appended to the log first. A caller (or a test) can always answer
//! "what changed, and in what order" by reading the log, rather than having
//! to infer history from the current state alone.
//!
//! Pausing carries a second guarantee beyond the log (PRD FR-1.3): every
//! transition also flips a [`super::PauseSignal`] as its first observable
//! effect, so a real-time audio callback holding a handle from
//! [`CaptureStateMachine::pause_signal`] sees a pause take effect within one
//! buffer period without ever touching a lock.

use std::fmt;

use super::signal::PauseSignal;

/// The three states a capture session can be in at any moment.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureState {
    /// No capture in progress; nothing is being written to the ring buffer.
    Idle,
    /// Actively capturing audio.
    Capturing,
    /// Capture was started and then suspended without stopping the session
    /// outright — distinct from `Idle` because resuming returns to
    /// `Capturing` directly, without whatever setup starting from `Idle`
    /// requires.
    Paused,
}

impl fmt::Display for CaptureState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            CaptureState::Idle => "idle",
            CaptureState::Capturing => "capturing",
            CaptureState::Paused => "paused",
        };
        f.write_str(label)
    }
}

/// One recorded move of a [`CaptureStateMachine`] from one state to another,
/// tagged with its position in the machine's log so callers can talk about
/// "the transition at index N" without re-deriving order from a `Vec`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CaptureTransitionEvent {
    pub sequence: u64,
    pub from: CaptureState,
    pub to: CaptureState,
}

impl fmt::Display for CaptureTransitionEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[{}] {} -> {}", self.sequence, self.from, self.to)
    }
}

/// Raised when a caller asks for a transition the state machine has no edge
/// for, e.g. pausing an already-idle session. Carries enough to explain the
/// rejection without the caller needing to have tracked `from` itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidTransition {
    pub from: CaptureState,
    pub attempted: CaptureState,
}

impl fmt::Display for InvalidTransition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "cannot transition from {} to {}",
            self.from, self.attempted
        )
    }
}

impl std::error::Error for InvalidTransition {}

/// Drives a capture session through idle/capturing/paused and keeps the
/// append-only log of every transition that has ever happened to it.
///
/// There is deliberately no way to set `state` directly — the only entry
/// points are `start`/`pause`/`resume`/`stop`, and each one either records a
/// transition or fails with [`InvalidTransition`] and leaves the state
/// (and the log) untouched.
pub struct CaptureStateMachine {
    state: CaptureState,
    log: Vec<CaptureTransitionEvent>,
    signal: PauseSignal,
}

impl CaptureStateMachine {
    /// A freshly constructed session always starts `Idle` with an empty log
    /// and a not-paused [`PauseSignal`].
    pub fn new() -> Self {
        Self {
            state: CaptureState::Idle,
            log: Vec::new(),
            signal: PauseSignal::new(),
        }
    }

    /// The state this session is in right now.
    pub fn state(&self) -> CaptureState {
        self.state
    }

    /// A cheap, cloneable handle onto this session's pause bit, safe to hand
    /// to a real-time audio callback (PRD FR-1.3). The handle stays live and
    /// current for the session's whole lifetime — every future transition on
    /// this machine updates the same underlying atomic every clone shares.
    pub fn pause_signal(&self) -> PauseSignal {
        self.signal.clone()
    }

    /// Every transition this session has undergone, oldest first. Reading
    /// this is the only way to see history — `state()` alone only ever shows
    /// the present.
    pub fn log(&self) -> &[CaptureTransitionEvent] {
        &self.log
    }

    /// Idle -> Capturing.
    pub fn start(&mut self) -> Result<CaptureTransitionEvent, InvalidTransition> {
        self.transition(&[CaptureState::Idle], CaptureState::Capturing)
    }

    /// Capturing -> Paused.
    pub fn pause(&mut self) -> Result<CaptureTransitionEvent, InvalidTransition> {
        self.transition(&[CaptureState::Capturing], CaptureState::Paused)
    }

    /// Paused -> Capturing. Distinct from `start`, which only accepts `Idle`
    /// as its source — the two land on the same `Capturing` state but are
    /// not interchangeable edges, since one implies capture setup just
    /// happened and the other implies it didn't.
    pub fn resume(&mut self) -> Result<CaptureTransitionEvent, InvalidTransition> {
        self.transition(&[CaptureState::Paused], CaptureState::Capturing)
    }

    /// Capturing or Paused -> Idle.
    pub fn stop(&mut self) -> Result<CaptureTransitionEvent, InvalidTransition> {
        self.transition(
            &[CaptureState::Capturing, CaptureState::Paused],
            CaptureState::Idle,
        )
    }

    /// Moves to `to` only if the machine is currently in one of `allowed_from`;
    /// otherwise leaves state and log untouched and reports the rejection.
    fn transition(
        &mut self,
        allowed_from: &[CaptureState],
        to: CaptureState,
    ) -> Result<CaptureTransitionEvent, InvalidTransition> {
        if !allowed_from.contains(&self.state) {
            return Err(InvalidTransition {
                from: self.state,
                attempted: to,
            });
        }
        let event = CaptureTransitionEvent {
            sequence: self.log.len() as u64,
            from: self.state,
            to,
        };
        self.state = to;
        // Flip the signal before anything else about this transition is
        // recorded: a single atomic store, so any reader polling
        // `pause_signal()` once per buffer period observes it on their very
        // next poll (PRD FR-1.3), well ahead of the `Vec` push below.
        self.signal.set(to == CaptureState::Paused);
        self.log.push(event);
        Ok(event)
    }
}

impl Default for CaptureStateMachine {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn starts_idle_with_an_empty_log() {
        let machine = CaptureStateMachine::new();
        assert_eq!(machine.state(), CaptureState::Idle);
        assert!(machine.log().is_empty());
    }

    #[test]
    fn start_pause_resume_stop_each_emit_a_transition_event() {
        let mut machine = CaptureStateMachine::new();

        let started = machine.start().expect("idle can start");
        assert_eq!(machine.state(), CaptureState::Capturing);
        assert_eq!(started.from, CaptureState::Idle);
        assert_eq!(started.to, CaptureState::Capturing);

        let paused = machine.pause().expect("capturing can pause");
        assert_eq!(machine.state(), CaptureState::Paused);
        assert_eq!(paused.from, CaptureState::Capturing);
        assert_eq!(paused.to, CaptureState::Paused);

        let resumed = machine.resume().expect("paused can resume");
        assert_eq!(machine.state(), CaptureState::Capturing);
        assert_eq!(resumed.from, CaptureState::Paused);
        assert_eq!(resumed.to, CaptureState::Capturing);

        let stopped = machine.stop().expect("capturing can stop");
        assert_eq!(machine.state(), CaptureState::Idle);
        assert_eq!(stopped.from, CaptureState::Capturing);
        assert_eq!(stopped.to, CaptureState::Idle);

        assert_eq!(
            machine.log(),
            &[started, paused, resumed, stopped],
            "every one of the four changes above must appear in the log, in order"
        );
    }

    #[test]
    fn stop_from_paused_also_returns_to_idle() {
        let mut machine = CaptureStateMachine::new();
        machine.start().unwrap();
        machine.pause().unwrap();

        let stopped = machine.stop().expect("paused can stop");
        assert_eq!(machine.state(), CaptureState::Idle);
        assert_eq!(stopped.from, CaptureState::Paused);
    }

    #[test]
    fn log_entries_carry_a_stable_increasing_sequence() {
        let mut machine = CaptureStateMachine::new();
        machine.start().unwrap();
        machine.pause().unwrap();
        machine.resume().unwrap();

        let sequences: Vec<u64> = machine.log().iter().map(|e| e.sequence).collect();
        assert_eq!(sequences, vec![0, 1, 2]);
    }

    #[test]
    fn pausing_while_idle_is_rejected_and_leaves_state_and_log_untouched() {
        let mut machine = CaptureStateMachine::new();

        let err = machine.pause().expect_err("cannot pause before starting");
        assert_eq!(err.from, CaptureState::Idle);
        assert_eq!(err.attempted, CaptureState::Paused);

        assert_eq!(machine.state(), CaptureState::Idle);
        assert!(machine.log().is_empty());
    }

    #[test]
    fn starting_while_already_capturing_is_rejected() {
        let mut machine = CaptureStateMachine::new();
        machine.start().unwrap();

        let err = machine.start().expect_err("cannot start twice");
        assert_eq!(err.from, CaptureState::Capturing);
        assert_eq!(err.attempted, CaptureState::Capturing);
        assert_eq!(
            machine.log().len(),
            1,
            "a rejected transition must not append to the log"
        );
    }

    #[test]
    fn resuming_while_idle_is_rejected() {
        let mut machine = CaptureStateMachine::new();
        let err = machine
            .resume()
            .expect_err("cannot resume without pausing first");
        assert_eq!(err.from, CaptureState::Idle);
        assert_eq!(err.attempted, CaptureState::Capturing);
    }

    #[test]
    fn stopping_while_idle_is_rejected() {
        let mut machine = CaptureStateMachine::new();
        let err = machine.stop().expect_err("nothing to stop while idle");
        assert_eq!(err.from, CaptureState::Idle);
        assert_eq!(err.attempted, CaptureState::Idle);
    }

    #[test]
    fn a_full_session_lifecycle_can_repeat() {
        let mut machine = CaptureStateMachine::new();
        for _ in 0..3 {
            machine.start().unwrap();
            machine.stop().unwrap();
        }
        assert_eq!(machine.state(), CaptureState::Idle);
        assert_eq!(machine.log().len(), 6);
    }

    #[test]
    fn display_impls_are_human_readable() {
        let mut machine = CaptureStateMachine::new();
        let started = machine.start().unwrap();
        assert_eq!(started.to_string(), "[0] idle -> capturing");

        let err = machine.start().unwrap_err();
        assert_eq!(
            err.to_string(),
            "cannot transition from capturing to capturing"
        );
    }

    #[test]
    fn a_fresh_machine_reports_a_not_paused_signal() {
        let machine = CaptureStateMachine::new();
        assert!(!machine.pause_signal().is_paused());
    }

    #[test]
    fn pause_flips_the_signal_and_resume_flips_it_back() {
        let mut machine = CaptureStateMachine::new();
        // Obtained before either transition, exactly like a real-time
        // callback would grab its handle once at session start.
        let signal = machine.pause_signal();

        machine.start().unwrap();
        assert!(!signal.is_paused(), "capturing must not read as paused");

        machine.pause().unwrap();
        assert!(signal.is_paused(), "pause must be visible on the pre-obtained handle");

        machine.resume().unwrap();
        assert!(!signal.is_paused(), "resume must clear the signal");
    }

    #[test]
    fn stop_from_paused_also_clears_the_signal() {
        let mut machine = CaptureStateMachine::new();
        let signal = machine.pause_signal();
        machine.start().unwrap();
        machine.pause().unwrap();
        assert!(signal.is_paused());

        machine.stop().unwrap();
        assert!(!signal.is_paused(), "a stopped session is not paused, it's gone");
    }

    #[test]
    fn a_rejected_transition_leaves_the_signal_untouched() {
        let mut machine = CaptureStateMachine::new();
        let signal = machine.pause_signal();

        // Pausing an idle session is rejected -- the signal must not move.
        machine.pause().unwrap_err();
        assert!(!signal.is_paused());
    }

    #[test]
    fn pause_takes_effect_within_one_buffer_period() {
        use super::super::signal::BUFFER_PERIOD;
        use std::time::Instant;

        let mut machine = CaptureStateMachine::new();
        let signal = machine.pause_signal();
        machine.start().unwrap();

        let started_pause = Instant::now();
        machine.pause().unwrap();
        // By the time `pause()` returns, the signal must already read
        // paused -- there is no window where a caller who just requested a
        // pause could poll the handle and still see capturing.
        assert!(signal.is_paused());
        let elapsed = started_pause.elapsed();

        assert!(
            elapsed < BUFFER_PERIOD,
            "pause must take effect within one buffer period ({:?}), took {:?}",
            BUFFER_PERIOD,
            elapsed
        );
    }
}
