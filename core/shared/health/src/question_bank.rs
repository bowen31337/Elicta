//! Question-bank startup validation (architecture §10, failure mode "Bank
//! empty or uncompiled": detection is *"Startup validation"*, behaviour is
//! *"Blocks meeting start with a clear message; degraded generic bank
//! offered"* (PRD FR-3.13)).
//!
//! A meeting that starts against an empty or never-compiled bank has nothing
//! to surface — the operator sees a silent, empty panel and has no way to
//! tell whether that means "no questions were needed" or "the compile step
//! never ran." Checking bank state before the meeting starts, rather than
//! discovering it live, turns that ambiguity into an explicit, actionable
//! block: compile the bank, or start from the degraded generic bank instead.

use std::fmt;

/// The compiled question bank's state as of just before a meeting starts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QuestionBankState {
    /// Whether an engagement-level compile (`POST
    /// /api/engagements/{id}/bank/compile`) has ever completed for this
    /// engagement.
    pub compiled: bool,
    /// Number of candidates the compiled bank holds. Meaningless while
    /// `compiled` is `false`, since an uncompiled bank has never populated
    /// this count.
    pub candidate_count: usize,
}

/// Result of validating the question bank before a meeting is allowed to
/// start.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QuestionBankStartupStatus {
    Ready { candidate_count: usize },
    Blocked(QuestionBankBlockedError),
}

/// Why the bank failed startup validation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QuestionBankBlockReason {
    /// No engagement-level compile has ever run.
    Uncompiled,
    /// A compile ran, but produced zero candidates.
    Empty,
}

/// The blocking error surfaced to the operator when the bank fails startup
/// validation, carrying enough detail to render PRD FR-3.13's "clear
/// message" and to say whether the degraded generic bank is an available
/// next step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuestionBankBlockedError {
    pub reason: QuestionBankBlockReason,
    pub generic_bank_available: bool,
}

impl fmt::Display for QuestionBankBlockedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let problem = match self.reason {
            QuestionBankBlockReason::Uncompiled => {
                "Question bank has not been compiled for this engagement"
            }
            QuestionBankBlockReason::Empty => {
                "Question bank is empty — the compile produced no candidates"
            }
        };
        let next_step = if self.generic_bank_available {
            "start with the degraded generic bank, or compile the bank and try again"
        } else {
            "compile the bank before starting this meeting"
        };
        write!(f, "Meeting start blocked: {problem}. {next_step}.")
    }
}

/// Validates the question bank against PRD FR-3.13 before a meeting starts.
/// Returns [`QuestionBankStartupStatus::Blocked`] when the bank was never
/// compiled or compiled to zero candidates, so the caller can block meeting
/// start with a clear message instead of starting a meeting with nothing to
/// surface. `generic_bank_available` reflects whether a degraded generic
/// elicitation bank (keyed to sector and project type, FR-3.13) can be
/// offered as a fallback, and only affects the error's message — it never
/// turns a block into a pass, since offering the generic bank is a distinct
/// operator choice this check does not make on their behalf.
pub fn validate_question_bank_at_startup(
    state: &QuestionBankState,
    generic_bank_available: bool,
) -> QuestionBankStartupStatus {
    if !state.compiled {
        return QuestionBankStartupStatus::Blocked(QuestionBankBlockedError {
            reason: QuestionBankBlockReason::Uncompiled,
            generic_bank_available,
        });
    }

    if state.candidate_count == 0 {
        return QuestionBankStartupStatus::Blocked(QuestionBankBlockedError {
            reason: QuestionBankBlockReason::Empty,
            generic_bank_available,
        });
    }

    QuestionBankStartupStatus::Ready {
        candidate_count: state.candidate_count,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_when_the_bank_has_never_been_compiled() {
        let state = QuestionBankState {
            compiled: false,
            candidate_count: 0,
        };

        let status = validate_question_bank_at_startup(&state, false);

        match status {
            QuestionBankStartupStatus::Blocked(error) => {
                assert_eq!(error.reason, QuestionBankBlockReason::Uncompiled);
            }
            other => panic!("expected a block for an uncompiled bank, got {other:?}"),
        }
    }

    #[test]
    fn blocks_when_the_compiled_bank_has_zero_candidates() {
        let state = QuestionBankState {
            compiled: true,
            candidate_count: 0,
        };

        let status = validate_question_bank_at_startup(&state, false);

        match status {
            QuestionBankStartupStatus::Blocked(error) => {
                assert_eq!(error.reason, QuestionBankBlockReason::Empty);
            }
            other => panic!("expected a block for an empty bank, got {other:?}"),
        }
    }

    #[test]
    fn passes_when_the_bank_is_compiled_with_candidates() {
        let state = QuestionBankState {
            compiled: true,
            candidate_count: 12,
        };

        let status = validate_question_bank_at_startup(&state, false);

        assert_eq!(
            status,
            QuestionBankStartupStatus::Ready {
                candidate_count: 12
            }
        );
    }

    #[test]
    fn uncompiled_takes_priority_over_the_empty_check() {
        // An uncompiled bank always reports candidate_count 0, so without an
        // explicit priority this would be ambiguous between "never
        // compiled" and "compiled but empty" — the two need different
        // operator-facing messages.
        let state = QuestionBankState {
            compiled: false,
            candidate_count: 0,
        };

        let status = validate_question_bank_at_startup(&state, false);

        assert_eq!(
            status,
            QuestionBankStartupStatus::Blocked(QuestionBankBlockedError {
                reason: QuestionBankBlockReason::Uncompiled,
                generic_bank_available: false,
            })
        );
    }

    #[test]
    fn blocked_message_names_the_problem_and_offers_the_generic_bank_when_available() {
        let error = QuestionBankBlockedError {
            reason: QuestionBankBlockReason::Empty,
            generic_bank_available: true,
        };

        let message = error.to_string();
        assert!(message.contains("empty"));
        assert!(message.contains("generic bank"));
    }

    #[test]
    fn blocked_message_omits_the_generic_bank_offer_when_unavailable() {
        let error = QuestionBankBlockedError {
            reason: QuestionBankBlockReason::Uncompiled,
            generic_bank_available: false,
        };

        let message = error.to_string();
        assert!(message.contains("not been compiled"));
        assert!(!message.contains("generic bank"));
    }

    #[test]
    fn generic_bank_availability_never_turns_a_block_into_a_pass() {
        let state = QuestionBankState {
            compiled: true,
            candidate_count: 0,
        };

        let status = validate_question_bank_at_startup(&state, true);

        assert!(matches!(status, QuestionBankStartupStatus::Blocked(_)));
    }
}
