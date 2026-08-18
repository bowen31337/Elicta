//! Meeting-resume status after an application restart (architecture §10,
//! failure mode "App crash": detection *"—"*, behaviour *"Session state
//! persisted per utterance; restart resumes"* (PRD NFR-4.3)).
//!
//! The session crate's store durably persists every utterance before it is
//! applied, so replaying that store at startup (architecture §3.4) is what
//! makes a restart survivable at all. That replay hands back two raw facts:
//! how many utterances were found, and whether the log's last record was
//! left incomplete by a crash mid-write. Neither fact is, by itself, what an
//! operator needs to see — this module turns them into the three outcomes
//! that actually matter: nothing to resume, a clean resume, or a resume that
//! lost the one utterance in flight when the crash happened. That last case
//! is surfaced explicitly rather than folded into a silent clean resume,
//! per the architecture's "fail loudly" rule: an operator who lost a
//! sentence of the transcript should be told, not left to notice later.

use std::fmt;

/// The operator-facing outcome of replaying persisted session state at
/// startup. Distinguishes a genuinely new meeting from a resumed one so a
/// caller never presents "no prior utterances" ambiguously — it always
/// means [`SessionResumeStatus::NoPriorSession`], never a resume that
/// happened to restore zero utterances.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionResumeStatus {
    /// The store held nothing durable — this is a new meeting, not a
    /// restart of an interrupted one.
    NoPriorSession,
    /// The meeting resumed with every previously durable utterance intact.
    Resumed { utterance_count: usize },
    /// The meeting resumed, but the store's last record was left
    /// incomplete by a crash mid-write: everything before it is intact,
    /// and exactly the one utterance being written when the process died
    /// is gone.
    ResumedWithGap { utterance_count: usize },
}

impl SessionResumeStatus {
    /// How many utterances the resumed meeting has, regardless of whether
    /// the resume was clean or lost the one utterance in flight. `0` for
    /// [`SessionResumeStatus::NoPriorSession`].
    pub fn utterance_count(&self) -> usize {
        match self {
            SessionResumeStatus::NoPriorSession => 0,
            SessionResumeStatus::Resumed { utterance_count }
            | SessionResumeStatus::ResumedWithGap { utterance_count } => *utterance_count,
        }
    }

    /// Whether this resume lost an utterance to a crash mid-write. `false`
    /// for both a clean resume and a fresh meeting.
    pub fn lost_an_utterance(&self) -> bool {
        matches!(self, SessionResumeStatus::ResumedWithGap { .. })
    }
}

impl fmt::Display for SessionResumeStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SessionResumeStatus::NoPriorSession => {
                write!(f, "Starting a new meeting — no prior session found")
            }
            SessionResumeStatus::Resumed { utterance_count } => {
                write!(
                    f,
                    "Resumed meeting: {utterance_count} prior utterance(s) restored"
                )
            }
            SessionResumeStatus::ResumedWithGap { utterance_count } => {
                write!(
                    f,
                    "Resumed meeting: {utterance_count} prior utterance(s) restored — \
                     1 utterance was lost when the app crashed mid-write"
                )
            }
        }
    }
}

/// Turns what a session store's replay found at startup into the resume
/// status an operator should see. `utterance_count` and `truncated_tail`
/// mirror the two facts a session store's load reports (architecture §3.4):
/// how many utterances were durable before this process started, and
/// whether the log's tail was cut off mid-write.
///
/// A `truncated_tail` of `true` always yields
/// [`SessionResumeStatus::ResumedWithGap`], even when `utterance_count` is
/// `0` — that combination means the very first utterance was being written
/// when the crash happened, which is still a meeting that was interrupted,
/// not a fresh one.
pub fn describe_session_resume(utterance_count: usize, truncated_tail: bool) -> SessionResumeStatus {
    if truncated_tail {
        return SessionResumeStatus::ResumedWithGap { utterance_count };
    }

    if utterance_count == 0 {
        return SessionResumeStatus::NoPriorSession;
    }

    SessionResumeStatus::Resumed { utterance_count }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_utterances_and_no_truncation_means_a_fresh_meeting() {
        let status = describe_session_resume(0, false);
        assert_eq!(status, SessionResumeStatus::NoPriorSession);
        assert_eq!(status.utterance_count(), 0);
        assert!(!status.lost_an_utterance());
    }

    #[test]
    fn prior_utterances_with_no_truncation_resume_cleanly() {
        let status = describe_session_resume(42, false);
        assert_eq!(status, SessionResumeStatus::Resumed { utterance_count: 42 });
        assert_eq!(status.utterance_count(), 42);
        assert!(!status.lost_an_utterance());
    }

    #[test]
    fn a_truncated_tail_reports_the_gap_even_with_utterances_restored() {
        let status = describe_session_resume(42, true);
        assert_eq!(
            status,
            SessionResumeStatus::ResumedWithGap { utterance_count: 42 }
        );
        assert_eq!(status.utterance_count(), 42);
        assert!(status.lost_an_utterance());
    }

    /// A crash before the very first utterance finished writing still means
    /// the meeting was interrupted, not that it never started — this must
    /// not collapse into `NoPriorSession`, which would tell the operator
    /// nothing happened when something did.
    #[test]
    fn a_truncated_tail_with_zero_restored_utterances_is_still_a_gap_not_a_fresh_start() {
        let status = describe_session_resume(0, true);
        assert_eq!(status, SessionResumeStatus::ResumedWithGap { utterance_count: 0 });
        assert!(status.lost_an_utterance());
    }

    #[test]
    fn fresh_meeting_message_says_no_prior_session_was_found() {
        let message = SessionResumeStatus::NoPriorSession.to_string();
        assert!(message.contains("new meeting"));
        assert!(message.contains("no prior session"));
    }

    #[test]
    fn clean_resume_message_names_the_restored_count_and_no_loss() {
        let message = SessionResumeStatus::Resumed { utterance_count: 7 }.to_string();
        assert!(message.contains('7'));
        assert!(!message.contains("crashed"));
    }

    #[test]
    fn gap_resume_message_names_the_restored_count_and_the_loss() {
        let message = SessionResumeStatus::ResumedWithGap { utterance_count: 7 }.to_string();
        assert!(message.contains('7'));
        assert!(message.contains("crashed mid-write"));
    }
}
