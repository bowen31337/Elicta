/// The `w₄·priority` term of the ranking formula (architecture §3.7).
///
/// `priority` here is the candidate's raw stored `priority` column
/// (architecture §3.6; `core/crates/bank`'s `store::BankCandidate::priority`,
/// `apps/service`'s `compiler/bank/models.py::BankCandidate.priority`) --
/// an integer assigned `1..N` across the bank where **lower is ranked
/// higher** (that field's own doc comment: "mirroring the ascending
/// `impact_rank` convention `OpenQuestion` already uses elsewhere in this
/// codebase"). Because this term enters the ranking sum with a *positive*
/// sign but a lower raw `priority` must produce a *larger* term, this
/// function inverts the value (`weight / priority`) rather than scaling it
/// directly the way `trigger_match_term`/`coverage_urgency_term`/
/// `authority_match_term` do -- those three already grow in the same
/// direction their sum needs, `priority` does not.
///
/// A non-positive `priority` (`<= 1`, violating the `>= 1` contract every
/// producer of this column enforces -- `BankCandidate.priority` is
/// `Field(ge=1)`) scores `0.0` rather than dividing by zero or amplifying
/// through a negative divisor, the same "malformed input degrades to
/// ranked last, never panics" contract `core/crates/bank`'s
/// `retrieval::cosine::cosine_similarity` uses for its own degenerate
/// inputs.
pub fn priority_term(priority: i64, weight: f32) -> f32 {
    if priority < 1 {
        return 0.0;
    }
    weight / priority as f32
}

/// Placeholder magnitude for the `w₄` weight, pending calibration against
/// the replay harness (architecture §9) -- uncalibrated, same caveat
/// attached to every other default weight/threshold in this module.
/// Architecture §3.7 is explicit that weights are configuration, not
/// hardcoded, so this constant is only ever a caller's fallback default,
/// never baked into `priority_term` itself.
pub const DEFAULT_PRIORITY_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_candidate_with_the_best_priority_scores_higher_than_a_worse_one() {
        let best = priority_term(1, DEFAULT_PRIORITY_WEIGHT);
        let worse = priority_term(10, DEFAULT_PRIORITY_WEIGHT);
        assert!(best > worse);
    }

    #[test]
    fn priority_term_decreases_monotonically_as_the_raw_priority_grows() {
        let p1 = priority_term(1, DEFAULT_PRIORITY_WEIGHT);
        let p2 = priority_term(2, DEFAULT_PRIORITY_WEIGHT);
        let p3 = priority_term(3, DEFAULT_PRIORITY_WEIGHT);
        assert!(p1 > p2 && p2 > p3);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_priority_entirely() {
        assert_eq!(priority_term(1, 0.0), priority_term(100, 0.0));
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(priority_term(2, 2.0), 1.0);
        assert_eq!(priority_term(2, 4.0), 2.0);
    }

    #[test]
    fn a_non_positive_priority_scores_zero_instead_of_dividing_by_zero() {
        assert_eq!(priority_term(0, DEFAULT_PRIORITY_WEIGHT), 0.0);
        assert_eq!(priority_term(-5, DEFAULT_PRIORITY_WEIGHT), 0.0);
    }

    #[test]
    fn the_default_weight_makes_a_better_priority_never_score_lower() {
        let best = priority_term(1, DEFAULT_PRIORITY_WEIGHT);
        let worse = priority_term(50, DEFAULT_PRIORITY_WEIGHT);
        assert!(best >= worse);
    }
}
