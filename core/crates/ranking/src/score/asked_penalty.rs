/// The `-asked_penalty` term of the ranking formula (architecture §3.7),
/// scoring PRD FR-6.7: once the operator taps the "Asked it" chip for a
/// thread, that thread's candidate should rank lower on future scoring
/// passes rather than keep competing with never-asked threads for the
/// operator's attention.
///
/// `is_asked` here is an already-computed plain `bool` -- whichever caller
/// assembles [`super::candidate_score::CandidateScoreInputs`] reads it from
/// wherever "Asked it" state lives (the `coverage_slots.satisfied_at`
/// column, per that migration's own doc comment, records the same tap this
/// term reacts to), the same "pure function, no I/O" contract architecture
/// §3.7 requires of every other term in this module. This function performs
/// no lookup of its own.
///
/// Unlike every other term in this crate, this one enters the ranking sum
/// with a *negative* contribution: an asked thread's term is `-weight`,
/// pulling its total score down rather than up, and an unasked thread's
/// term is `0.0` -- leaving the rest of the sum untouched. That sign is the
/// whole point of a *penalty* term, as opposed to `trigger_match_term`/
/// `coverage_urgency_term`/`authority_match_term`/`priority_term`, which all
/// reward rather than punish.
pub fn asked_penalty_term(is_asked: bool, weight: f32) -> f32 {
    if is_asked {
        -weight
    } else {
        0.0
    }
}

/// Placeholder magnitude for the asked-penalty weight, pending calibration
/// against the replay harness (architecture §9) -- uncalibrated, same
/// caveat attached to every other default weight/threshold in this module.
/// Architecture §3.7 is explicit that weights are configuration, not
/// hardcoded, so this constant is only ever a caller's fallback default,
/// never baked into `asked_penalty_term` itself.
pub const DEFAULT_ASKED_PENALTY_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_asked_thread_scores_lower_than_an_unasked_one() {
        let asked = asked_penalty_term(true, DEFAULT_ASKED_PENALTY_WEIGHT);
        let unasked = asked_penalty_term(false, DEFAULT_ASKED_PENALTY_WEIGHT);
        assert!(asked < unasked);
    }

    #[test]
    fn an_unasked_thread_contributes_nothing() {
        assert_eq!(asked_penalty_term(false, DEFAULT_ASKED_PENALTY_WEIGHT), 0.0);
    }

    #[test]
    fn an_asked_thread_contributes_the_negative_weight() {
        assert_eq!(asked_penalty_term(true, 2.5), -2.5);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_asked_state_entirely() {
        assert_eq!(asked_penalty_term(true, 0.0), asked_penalty_term(false, 0.0));
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(asked_penalty_term(true, 1.0), -1.0);
        assert_eq!(asked_penalty_term(true, 3.0), -3.0);
    }
}
