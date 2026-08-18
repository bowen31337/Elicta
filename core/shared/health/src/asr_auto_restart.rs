//! Auto-restart orchestration for a crashed ASR backend (architecture §10,
//! failure mode "ASR backend crash": behaviour *"Visible error, auto-restart,
//! gap marked in transcript"* (PRD NFR-4.2: "ASR failure surfaces visibly
//! rather than silently producing an empty transcript")).
//!
//! [`AsrHeartbeatMonitor`](crate::AsrHeartbeatMonitor) detects the crash and
//! marks the transcript gap; this module drives what happens next. A restart
//! that just quietly retries in the background reintroduces exactly the
//! silent failure NFR-4.2 rules out — an operator watching a transcript that
//! has stopped growing can't tell a backend that's about to recover from one
//! that's stuck retrying forever. [`AsrAutoRestarter`] keeps a labeled,
//! visible [`AsrRestartStatus`] for every attempt, so there is always
//! something on screen in place of the empty transcript: "restarting"
//! (naming which attempt), or, once attempts are exhausted, a persistent
//! error asking for operator intervention rather than a restart loop no one
//! can see.

use std::fmt;
use std::time::Duration;

/// How many restart attempts are made before giving up and surfacing a
/// persistent error that needs operator attention.
pub const DEFAULT_MAX_RESTART_ATTEMPTS: u32 = 3;

/// Fixed delay between one restart attempt and the next.
pub const DEFAULT_RESTART_RETRY_INTERVAL: Duration = Duration::from_secs(5);

/// The visible status of an in-progress (or exhausted) auto-restart — what a
/// caller renders to the operator in place of the empty transcript a silent
/// restart would otherwise leave behind.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AsrRestartStatus {
    /// A restart attempt is scheduled or in flight. `attempt` is
    /// 1-indexed; `retry_at` is when this attempt was (or will be) made.
    Restarting { attempt: u32, retry_at: Duration },
    /// The backend has been heard from again; the connection is healthy.
    Recovered,
    /// Every attempt up to the configured maximum failed; auto-restart has
    /// stopped and needs operator intervention.
    GaveUp { attempts: u32 },
}

impl fmt::Display for AsrRestartStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AsrRestartStatus::Restarting { attempt, retry_at } => write!(
                f,
                "ASR connection lost — restarting (attempt {}) at {:?}...",
                attempt, retry_at,
            ),
            AsrRestartStatus::Recovered => write!(f, "ASR connection restored."),
            AsrRestartStatus::GaveUp { attempts } => write!(
                f,
                "ASR connection error — auto-restart failed after {} attempt(s). Manual restart required.",
                attempts,
            ),
        }
    }
}

/// Drives the auto-restart sequence after
/// [`AsrHeartbeatMonitor`](crate::AsrHeartbeatMonitor) reports a crash,
/// tracking attempts against a fixed cap and holding a visible
/// [`AsrRestartStatus`] at every step. Driven by explicit calls rather than
/// a background timer, matching every other backend wrapper in this
/// codebase (`asr-live`'s `KeepaliveBackend` and `AsrHeartbeatMonitor`
/// alike): this crate is synchronous and non-networked, so whatever drives
/// real wall time and actually reopens the connection lives outside it.
#[derive(Debug, Clone)]
pub struct AsrAutoRestarter {
    max_attempts: u32,
    retry_interval: Duration,
    status: Option<AsrRestartStatus>,
}

impl AsrAutoRestarter {
    /// Starts a restarter that gives up after `max_attempts` failed
    /// attempts, retrying every `retry_interval`.
    pub fn new(max_attempts: u32, retry_interval: Duration) -> Self {
        Self {
            max_attempts,
            retry_interval,
            status: None,
        }
    }

    /// Starts a restarter using [`DEFAULT_MAX_RESTART_ATTEMPTS`] and
    /// [`DEFAULT_RESTART_RETRY_INTERVAL`].
    pub fn with_defaults() -> Self {
        Self::new(DEFAULT_MAX_RESTART_ATTEMPTS, DEFAULT_RESTART_RETRY_INTERVAL)
    }

    /// The current visible status, or `None` before any crash has ever been
    /// observed.
    pub fn status(&self) -> Option<AsrRestartStatus> {
        self.status
    }

    /// Called the moment a crash is detected: begins the restart sequence
    /// at attempt 1, scheduled for `now`, and returns the resulting visible
    /// status.
    pub fn crash_detected(&mut self, now: Duration) -> AsrRestartStatus {
        let status = AsrRestartStatus::Restarting {
            attempt: 1,
            retry_at: now,
        };
        self.status = Some(status);
        status
    }

    /// Called when a scheduled restart attempt itself fails to reconnect.
    /// Advances to the next attempt, scheduled `retry_interval` later, or —
    /// once `max_attempts` is exhausted — gives up with a persistent error.
    /// Returns `None` if called while no restart is in progress (already
    /// recovered, given up, or none was ever started).
    pub fn attempt_failed(&mut self, now: Duration) -> Option<AsrRestartStatus> {
        let Some(AsrRestartStatus::Restarting { attempt, .. }) = self.status else {
            return None;
        };

        let status = if attempt >= self.max_attempts {
            AsrRestartStatus::GaveUp { attempts: attempt }
        } else {
            AsrRestartStatus::Restarting {
                attempt: attempt + 1,
                retry_at: now + self.retry_interval,
            }
        };
        self.status = Some(status);
        Some(status)
    }

    /// Called when the backend is heard from again (a heartbeat resumes):
    /// closes out the restart sequence as recovered. Returns `None` if no
    /// restart had ever been started.
    pub fn recovered(&mut self) -> Option<AsrRestartStatus> {
        self.status?;
        self.status = Some(AsrRestartStatus::Recovered);
        Some(AsrRestartStatus::Recovered)
    }

    /// Whether auto-restart has exhausted its attempts and needs operator
    /// intervention.
    pub fn has_given_up(&self) -> bool {
        matches!(self.status, Some(AsrRestartStatus::GaveUp { .. }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_status_is_reported_before_any_crash_is_observed() {
        let restarter = AsrAutoRestarter::with_defaults();

        assert_eq!(restarter.status(), None);
        assert!(!restarter.has_given_up());
    }

    #[test]
    fn a_crash_starts_the_restart_sequence_at_attempt_one() {
        let mut restarter = AsrAutoRestarter::new(3, Duration::from_secs(5));

        let status = restarter.crash_detected(Duration::from_secs(15));

        assert_eq!(
            status,
            AsrRestartStatus::Restarting {
                attempt: 1,
                retry_at: Duration::from_secs(15)
            }
        );
        assert_eq!(restarter.status(), Some(status));
    }

    #[test]
    fn a_failed_attempt_advances_to_the_next_attempt_after_the_retry_interval() {
        let mut restarter = AsrAutoRestarter::new(3, Duration::from_secs(5));
        restarter.crash_detected(Duration::from_secs(15));

        let status = restarter
            .attempt_failed(Duration::from_secs(20))
            .expect("a restart is in progress");

        assert_eq!(
            status,
            AsrRestartStatus::Restarting {
                attempt: 2,
                retry_at: Duration::from_secs(25)
            }
        );
    }

    #[test]
    fn exhausting_every_attempt_surfaces_a_persistent_give_up_error() {
        let mut restarter = AsrAutoRestarter::new(2, Duration::from_secs(5));
        restarter.crash_detected(Duration::from_secs(0));
        restarter
            .attempt_failed(Duration::from_secs(5))
            .expect("first failure advances to attempt 2");

        let status = restarter
            .attempt_failed(Duration::from_secs(10))
            .expect("second attempt is still in progress");

        assert_eq!(status, AsrRestartStatus::GaveUp { attempts: 2 });
        assert!(restarter.has_given_up());
    }

    #[test]
    fn a_failed_attempt_with_no_restart_in_progress_reports_nothing() {
        let mut restarter = AsrAutoRestarter::with_defaults();

        let status = restarter.attempt_failed(Duration::from_secs(5));

        assert!(status.is_none());
    }

    #[test]
    fn recovery_closes_out_an_in_progress_restart() {
        let mut restarter = AsrAutoRestarter::new(3, Duration::from_secs(5));
        restarter.crash_detected(Duration::from_secs(15));

        let status = restarter.recovered().expect("a restart was in progress");

        assert_eq!(status, AsrRestartStatus::Recovered);
        assert_eq!(restarter.status(), Some(AsrRestartStatus::Recovered));
    }

    #[test]
    fn recovery_with_no_restart_ever_started_reports_nothing() {
        let mut restarter = AsrAutoRestarter::with_defaults();

        assert!(restarter.recovered().is_none());
    }

    #[test]
    fn a_crash_after_recovery_restarts_the_attempt_count_from_one() {
        let mut restarter = AsrAutoRestarter::new(3, Duration::from_secs(5));
        restarter.crash_detected(Duration::from_secs(0));
        restarter.attempt_failed(Duration::from_secs(5));
        restarter.recovered();

        let status = restarter.crash_detected(Duration::from_secs(60));

        assert_eq!(
            status,
            AsrRestartStatus::Restarting {
                attempt: 1,
                retry_at: Duration::from_secs(60)
            }
        );
    }

    #[test]
    fn restarting_status_message_names_the_attempt_and_is_clearly_an_error() {
        let status = AsrRestartStatus::Restarting {
            attempt: 2,
            retry_at: Duration::from_secs(20),
        };

        let message = status.to_string();
        assert!(message.contains("restarting"));
        assert!(message.contains("attempt 2"));
    }

    #[test]
    fn gave_up_status_message_asks_for_manual_intervention() {
        let status = AsrRestartStatus::GaveUp { attempts: 3 };

        let message = status.to_string();
        assert!(message.contains("auto-restart failed"));
        assert!(message.contains("Manual restart required"));
    }

    #[test]
    fn recovered_status_message_confirms_restoration() {
        let status = AsrRestartStatus::Recovered;

        assert!(status.to_string().contains("restored"));
    }

    #[test]
    fn with_defaults_uses_the_documented_constants() {
        let mut restarter = AsrAutoRestarter::with_defaults();
        restarter.crash_detected(Duration::ZERO);

        for attempt in 1..DEFAULT_MAX_RESTART_ATTEMPTS {
            let status = restarter
                .attempt_failed(Duration::ZERO)
                .expect("still restarting");
            assert_eq!(
                status,
                AsrRestartStatus::Restarting {
                    attempt: attempt + 1,
                    retry_at: DEFAULT_RESTART_RETRY_INTERVAL,
                }
            );
        }

        let final_status = restarter
            .attempt_failed(Duration::ZERO)
            .expect("last attempt still in progress");
        assert_eq!(
            final_status,
            AsrRestartStatus::GaveUp {
                attempts: DEFAULT_MAX_RESTART_ATTEMPTS
            }
        );
    }
}
