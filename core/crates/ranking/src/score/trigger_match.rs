/// The `w₁·trigger_match` term of the ranking formula (architecture §3.7),
/// scoring how well a candidate's trigger matched the live utterance.
///
/// `trigger_match` here is the already-computed cosine similarity from
/// `core/crates/bank`'s `retrieval::cosine::retrieve_ranked_candidates` --
/// that module's own `HANDOFF.md` is explicit that "this module's cosine
/// score is one input to [the ranking] formula's `trigger_match`/similarity
/// term, not the final candidate score." Architecture §3.7 independently
/// requires the ranking formula to be a "pure function, no I/O beyond the
/// local index," so this function takes `trigger_match` as a plain `f32`
/// argument rather than recomputing similarity itself, mirroring
/// `authority_match_term`'s precedent for the same reason.
///
/// Because this term enters the ranking sum with a positive sign and
/// `trigger_match` only grows as a candidate's embedding aligns more closely
/// with the query, a more closely matched candidate always contributes at
/// least as much to the total score as an otherwise-identical, less closely
/// matched one -- see `a_more_closely_matched_candidate_scores_higher`
/// below.
pub fn trigger_match_term(trigger_match: f32, weight: f32) -> f32 {
    weight * trigger_match
}

/// Placeholder magnitude for the `w₁` weight, pending calibration against
/// the replay harness (architecture §9) -- uncalibrated, same caveat
/// attached to every other default weight/threshold across sibling crates,
/// including this module's own `DEFAULT_AUTHORITY_MATCH_WEIGHT`.
/// Architecture §3.7 is explicit that weights are configuration, not
/// hardcoded, so this constant is only ever a caller's fallback default,
/// never baked into `trigger_match_term` itself.
pub const DEFAULT_TRIGGER_MATCH_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_more_closely_matched_candidate_scores_higher() {
        let close = trigger_match_term(0.9, DEFAULT_TRIGGER_MATCH_WEIGHT);
        let far = trigger_match_term(0.1, DEFAULT_TRIGGER_MATCH_WEIGHT);
        assert!(close > far);
    }

    #[test]
    fn an_orthogonal_candidate_scores_between_a_matched_and_an_opposite_one() {
        let matched = trigger_match_term(1.0, DEFAULT_TRIGGER_MATCH_WEIGHT);
        let orthogonal = trigger_match_term(0.0, DEFAULT_TRIGGER_MATCH_WEIGHT);
        let opposite = trigger_match_term(-1.0, DEFAULT_TRIGGER_MATCH_WEIGHT);
        assert!(opposite < orthogonal && orthogonal < matched);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_the_match_entirely() {
        assert_eq!(trigger_match_term(1.0, 0.0), trigger_match_term(-1.0, 0.0));
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(trigger_match_term(1.0, 2.0), 2.0);
        assert_eq!(trigger_match_term(0.5, 2.0), 1.0);
    }

    #[test]
    fn the_default_weight_makes_a_higher_match_never_score_lower() {
        let matched = trigger_match_term(1.0, DEFAULT_TRIGGER_MATCH_WEIGHT);
        let unmatched = trigger_match_term(0.0, DEFAULT_TRIGGER_MATCH_WEIGHT);
        assert!(matched >= unmatched);
    }
}
