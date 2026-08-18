/// The `-w₅·recency_penalty` term of the ranking formula (architecture
/// §3.7: "score = w₁·trigger_match + w₂·coverage_urgency +
/// w₃·authority_match + w₄·priority − w₅·recency_penalty −
/// w₆·asked_penalty"), scoring this feature: "System subtracts a recency
/// penalty when a similar nudge was surfaced recently in the same
/// meeting."
///
/// `was_recently_surfaced` here is an already-computed plain `bool` --
/// whichever caller assembles [`super::candidate_score::CandidateScoreInputs`]
/// decides whether a similar nudge counts as "recently surfaced" (e.g. by
/// comparing a stored `lastSurfacedAt` against the current time and some
/// recency window), the same "pure function, no I/O" contract architecture
/// §3.7 requires of every other term in this module. This function performs
/// no lookup or clock read of its own -- no module in this repo tracks
/// recently-surfaced nudges yet (`candidate_score.rs`'s own doc comment),
/// so this term is written against the contract that tracker will
/// eventually satisfy, mirroring how `asked_penalty_term` was written
/// before "Asked it" state existed.
///
/// Like `asked_penalty_term`, this term enters the ranking sum with a
/// *negative* contribution: a recently-surfaced thread's term is
/// `-weight`, pulling its total score down rather than up, and a thread
/// with no recent similar nudge scores `0.0` -- leaving the rest of the sum
/// untouched.
pub fn recency_penalty_term(was_recently_surfaced: bool, weight: f32) -> f32 {
    if was_recently_surfaced {
        -weight
    } else {
        0.0
    }
}

/// Placeholder magnitude for the recency-penalty weight, pending
/// calibration against the replay harness (architecture §9) -- uncalibrated,
/// same caveat attached to every other default weight/threshold in this
/// module. Architecture §3.7 is explicit that weights are configuration,
/// not hardcoded, so this constant is only ever a caller's fallback
/// default, never baked into `recency_penalty_term` itself.
pub const DEFAULT_RECENCY_PENALTY_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_recently_surfaced_thread_scores_lower_than_one_that_was_not() {
        let recent = recency_penalty_term(true, DEFAULT_RECENCY_PENALTY_WEIGHT);
        let not_recent = recency_penalty_term(false, DEFAULT_RECENCY_PENALTY_WEIGHT);
        assert!(recent < not_recent);
    }

    #[test]
    fn a_thread_with_no_recent_similar_nudge_contributes_nothing() {
        assert_eq!(
            recency_penalty_term(false, DEFAULT_RECENCY_PENALTY_WEIGHT),
            0.0
        );
    }

    #[test]
    fn a_recently_surfaced_thread_contributes_the_negative_weight() {
        assert_eq!(recency_penalty_term(true, 2.5), -2.5);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_recency_entirely() {
        assert_eq!(
            recency_penalty_term(true, 0.0),
            recency_penalty_term(false, 0.0)
        );
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(recency_penalty_term(true, 1.0), -1.0);
        assert_eq!(recency_penalty_term(true, 3.0), -3.0);
    }
}
