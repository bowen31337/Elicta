//! ASR backend crash detection via event-stream heartbeat (architecture
//! §10, failure mode "ASR backend crash": detection *"Heartbeat on the
//! event stream"*, behaviour *"Visible error, auto-restart, gap marked in
//! transcript"* (PRD NFR-4.2: "ASR failure surfaces visibly rather than
//! silently producing an empty transcript")).
//!
//! A crashed ASR backend does not announce itself — the connection just
//! stops emitting events. Without a heartbeat, a quiet backend is
//! indistinguishable from a quiet room, and the operator would keep
//! trusting a transcript that has silently stopped growing. Timing out on
//! the event stream's heartbeat turns that silence into a detected crash,
//! anchored to the exact instant silence tipped over the threshold — that
//! instant is what [`TranscriptGapMarker::crashed_at`] records, so the gap
//! left in the transcript can be marked at the failure point itself rather
//! than at whenever someone happens to notice.

use std::fmt;
use std::time::Duration;

/// How long the event stream may go without a heartbeat before its backend
/// is treated as crashed rather than merely between utterances.
pub const DEFAULT_HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(15);

/// The record placed into the transcript for the stretch an ASR backend
/// crash left untranscribed: everything before `crashed_at` is
/// trustworthy, and nothing between `crashed_at` and `resumed_at` was
/// transcribed at all (PRD NFR-4.2). `resumed_at` is `None` while the gap
/// is still open — the backend hasn't sent a heartbeat since the crash was
/// detected — and is filled in the moment [`AsrHeartbeatMonitor`] observes
/// the auto-restarted backend come back.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TranscriptGapMarker {
    pub crashed_at: Duration,
    pub resumed_at: Option<Duration>,
}

impl TranscriptGapMarker {
    /// How long the gap lasted, once closed. `None` while still open.
    pub fn duration(&self) -> Option<Duration> {
        self.resumed_at
            .map(|resumed| resumed.saturating_sub(self.crashed_at))
    }

    /// Whether the backend has not yet been heard from since the crash.
    pub fn is_open(&self) -> bool {
        self.resumed_at.is_none()
    }
}

impl fmt::Display for TranscriptGapMarker {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.resumed_at {
            Some(resumed) => write!(
                f,
                "[Transcript gap: ASR backend crashed at {:?}, resumed at {:?}]",
                self.crashed_at, resumed,
            ),
            None => write!(
                f,
                "[Transcript gap: ASR backend crashed at {:?}, not yet resumed]",
                self.crashed_at,
            ),
        }
    }
}

/// The alert surfaced to the operator the moment a crash is detected —
/// visible rather than silent (PRD NFR-4.2), paired with the
/// [`TranscriptGapMarker`] recording exactly where the resulting gap
/// starts in the transcript.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AsrBackendCrashAlert {
    pub gap: TranscriptGapMarker,
}

impl fmt::Display for AsrBackendCrashAlert {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "ASR backend crashed at {:?} — auto-restarting; the gap is marked in the transcript.",
            self.gap.crashed_at,
        )
    }
}

/// Tracks an ASR event stream's heartbeat and turns silence past `timeout`
/// into a detected crash. Driven by explicit calls rather than a
/// background timer, matching every other backend wrapper in this
/// codebase (`asr-live`'s `KeepaliveBackend` and friends): this crate is
/// synchronous and non-networked, so whatever drives real wall time lives
/// outside it.
#[derive(Debug, Clone)]
pub struct AsrHeartbeatMonitor {
    timeout: Duration,
    last_heartbeat_at: Duration,
    open_gap: Option<TranscriptGapMarker>,
}

impl AsrHeartbeatMonitor {
    /// Starts a monitor whose clock begins at zero, timing out after
    /// `timeout` of silence.
    pub fn new(timeout: Duration) -> Self {
        Self {
            timeout,
            last_heartbeat_at: Duration::ZERO,
            open_gap: None,
        }
    }

    /// Starts a monitor using [`DEFAULT_HEARTBEAT_TIMEOUT`].
    pub fn with_default_timeout() -> Self {
        Self::new(DEFAULT_HEARTBEAT_TIMEOUT)
    }

    /// Whether a crash is currently detected and its gap still open.
    pub fn is_crashed(&self) -> bool {
        self.open_gap.is_some()
    }

    /// Records a heartbeat (or any other event) received on the stream at
    /// `now`. If a gap was open, this is the backend coming back from its
    /// auto-restart: the gap closes with `resumed_at` set to `now`, and
    /// the closed marker is returned so the caller can finalise it in the
    /// transcript. Returns `None` when the stream was already healthy.
    pub fn record_heartbeat(&mut self, now: Duration) -> Option<TranscriptGapMarker> {
        self.last_heartbeat_at = now;
        self.open_gap.take().map(|gap| TranscriptGapMarker {
            resumed_at: Some(now),
            ..gap
        })
    }

    /// Advances the monitor's view of the current time to `now` without a
    /// heartbeat having arrived. If the stream has now been silent for at
    /// least `timeout`, opens a gap anchored at the failure point —
    /// `last_heartbeat_at + timeout`, the instant silence actually tipped
    /// over the threshold, not `now`, which only reflects when this check
    /// happened to run — and returns the resulting alert. Returns `None`
    /// when the stream is still within its timeout, or when a gap is
    /// already open (a crash is only detected once; use
    /// [`AsrHeartbeatMonitor::record_heartbeat`] to close it).
    pub fn check(&mut self, now: Duration) -> Option<AsrBackendCrashAlert> {
        if self.open_gap.is_some() {
            return None;
        }

        let silent_for = now.saturating_sub(self.last_heartbeat_at);
        if silent_for < self.timeout {
            return None;
        }

        let gap = TranscriptGapMarker {
            crashed_at: self.last_heartbeat_at + self.timeout,
            resumed_at: None,
        };
        self.open_gap = Some(gap);
        Some(AsrBackendCrashAlert { gap })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_crash_is_detected_while_heartbeats_stay_within_the_timeout() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));

        let alert = monitor.check(Duration::from_secs(10));

        assert!(alert.is_none());
        assert!(!monitor.is_crashed());
    }

    #[test]
    fn a_crash_is_detected_the_moment_the_timeout_is_reached() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));

        let alert = monitor.check(Duration::from_secs(15));

        assert!(alert.is_some());
        assert!(monitor.is_crashed());
    }

    #[test]
    fn the_gap_marker_is_anchored_at_the_failure_point_not_the_check_time() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));

        let alert = monitor
            .check(Duration::from_secs(40))
            .expect("silence far exceeds the timeout");

        assert_eq!(
            alert.gap.crashed_at,
            Duration::from_secs(15),
            "the failure point is when silence first hit the timeout, not when check() ran"
        );
    }

    #[test]
    fn a_freshly_started_monitor_is_not_falsely_flagged() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));

        let alert = monitor.check(Duration::from_secs(14));

        assert!(alert.is_none());
    }

    #[test]
    fn a_detected_crash_is_not_reported_again_on_a_later_check() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));
        monitor
            .check(Duration::from_secs(15))
            .expect("first check detects the crash");

        let second = monitor.check(Duration::from_secs(30));

        assert!(second.is_none(), "the crash is only reported once, not on every subsequent check");
        assert!(monitor.is_crashed());
    }

    #[test]
    fn a_heartbeat_after_a_crash_closes_the_gap_and_resets_the_clock() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));
        monitor.check(Duration::from_secs(15)).expect("crash detected");

        let closed = monitor
            .record_heartbeat(Duration::from_secs(20))
            .expect("the heartbeat closes the open gap");

        assert_eq!(closed.crashed_at, Duration::from_secs(15));
        assert_eq!(closed.resumed_at, Some(Duration::from_secs(20)));
        assert_eq!(closed.duration(), Some(Duration::from_secs(5)));
        assert!(!closed.is_open());
        assert!(!monitor.is_crashed());
    }

    #[test]
    fn a_heartbeat_while_healthy_reports_no_gap_to_close() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));

        let closed = monitor.record_heartbeat(Duration::from_secs(5));

        assert!(closed.is_none());
    }

    #[test]
    fn the_monitor_can_detect_a_second_crash_after_recovering_from_the_first() {
        let mut monitor = AsrHeartbeatMonitor::new(Duration::from_secs(15));
        monitor.check(Duration::from_secs(15)).expect("first crash detected");
        monitor
            .record_heartbeat(Duration::from_secs(20))
            .expect("first crash closes");

        let second_alert = monitor.check(Duration::from_secs(36));

        assert!(second_alert.is_some());
        assert_eq!(
            second_alert.unwrap().gap.crashed_at,
            Duration::from_secs(35),
            "the second timeout is measured from the heartbeat that closed the first gap"
        );
    }

    #[test]
    fn an_open_gap_reports_no_duration_yet() {
        let gap = TranscriptGapMarker { crashed_at: Duration::from_secs(15), resumed_at: None };

        assert!(gap.is_open());
        assert_eq!(gap.duration(), None);
    }

    #[test]
    fn crash_alert_message_names_the_failure_point_and_the_auto_restart() {
        let alert = AsrBackendCrashAlert {
            gap: TranscriptGapMarker { crashed_at: Duration::from_secs(15), resumed_at: None },
        };

        let message = alert.to_string();
        assert!(message.contains("crashed"));
        assert!(message.contains("auto-restarting"));
        assert!(message.contains("marked in the transcript"));
    }

    #[test]
    fn open_gap_marker_message_says_it_has_not_resumed() {
        let gap = TranscriptGapMarker { crashed_at: Duration::from_secs(15), resumed_at: None };

        let message = gap.to_string();
        assert!(message.contains("not yet resumed"));
    }

    #[test]
    fn closed_gap_marker_message_names_both_endpoints() {
        let gap = TranscriptGapMarker {
            crashed_at: Duration::from_secs(15),
            resumed_at: Some(Duration::from_secs(20)),
        };

        let message = gap.to_string();
        assert!(message.contains("crashed"));
        assert!(message.contains("resumed"));
    }

    #[test]
    fn with_default_timeout_uses_the_documented_heartbeat_timeout() {
        let mut monitor = AsrHeartbeatMonitor::with_default_timeout();

        let too_early = monitor.check(DEFAULT_HEARTBEAT_TIMEOUT - Duration::from_millis(1));
        assert!(too_early.is_none());

        let alert = monitor.check(DEFAULT_HEARTBEAT_TIMEOUT);
        assert!(alert.is_some());
    }
}
