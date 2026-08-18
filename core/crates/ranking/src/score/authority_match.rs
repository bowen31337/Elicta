/// The `w₃·authority_match` term of the ranking formula (architecture
/// §3.7), scoring PRD FR-4.7: "weight candidate ranking by attendee
/// decision authority and domain -- surface questions the people actually
/// in the room can answer."
///
/// `authority_match` here is the already-computed per-candidate value from
/// `apps/service/.../compiler/techniques/authority_matching.py`'s
/// `compute_candidate_authority_match`: `1.0` when every role a
/// candidate's authority_match tag names is present among the meeting's
/// actual attendees (matched by `role`, `business_function`,
/// `decision_authority`, or `domain_expertise` -- PRD FR-3.10), `0.0` when
/// none of them are, and proportional in between. That module's own
/// docstring is explicit about why this crate never re-derives the match
/// itself: "...persisted per candidate so ranking reads a plain number
/// rather than re-deriving it from the roster on every score." Architecture
/// §3.7 backs this up independently -- ranking is "Pure function, no I/O
/// beyond the local index" -- so this function takes `authority_match` as a
/// plain `f32` argument, never an attendee roster, and performs no role
/// matching of its own.
///
/// Because this term enters the ranking sum with a positive sign and
/// `authority_match` only grows as more of a candidate's named roles are
/// covered, a candidate whose authority_match names a role present in the
/// meeting's attendees always contributes at least as much to the total
/// score as an otherwise-identical candidate whose named roles are absent
/// -- see `a_candidate_with_a_matched_role_scores_higher_than_one_without`
/// below, the PRD FR-4.7 acceptance criterion made concrete.
pub fn authority_match_term(authority_match: f32, weight: f32) -> f32 {
    weight * authority_match
}

/// Placeholder magnitude for the `w₃` weight, pending calibration against
/// the replay harness (architecture §9) -- uncalibrated, same caveat
/// attached to every other default weight/threshold across sibling crates
/// (e.g. `language::tags::ExpectedLanguageSet`'s `outside_penalty`).
/// Architecture §3.7 is explicit that weights are configuration, not
/// hardcoded, so this constant is only ever a caller's fallback default,
/// never baked into `authority_match_term` itself.
pub const DEFAULT_AUTHORITY_MATCH_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_candidate_with_a_matched_role_scores_higher_than_one_without() {
        let matched = authority_match_term(1.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        let unmatched = authority_match_term(0.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        assert!(matched > unmatched);
    }

    #[test]
    fn a_partially_matched_candidate_scores_between_fully_matched_and_unmatched() {
        let full = authority_match_term(1.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        let half = authority_match_term(0.5, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        let none = authority_match_term(0.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        assert!(none < half && half < full);
    }

    #[test]
    fn a_candidate_with_no_authority_requirement_scores_the_full_term() {
        // compute_candidate_authority_match returns 1.0 for an empty
        // requirement list -- universally answerable, same as a fully
        // covered one.
        let universal = authority_match_term(1.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        assert_eq!(universal, DEFAULT_AUTHORITY_MATCH_WEIGHT);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_the_match_entirely() {
        assert_eq!(authority_match_term(1.0, 0.0), authority_match_term(0.0, 0.0));
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(authority_match_term(1.0, 2.0), 2.0);
        assert_eq!(authority_match_term(0.5, 2.0), 1.0);
    }

    #[test]
    fn the_default_weight_makes_a_higher_match_never_score_lower() {
        let matched = authority_match_term(1.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        let unmatched = authority_match_term(0.0, DEFAULT_AUTHORITY_MATCH_WEIGHT);
        assert!(matched >= unmatched);
    }
}
