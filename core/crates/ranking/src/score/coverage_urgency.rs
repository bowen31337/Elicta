/// The `w₂·coverage_urgency` term of the ranking formula (architecture
/// §3.7), scoring "unfilled section × time pressure" -- surfacing questions
/// for template sections that are both still empty and running out of time
/// to fill.
///
/// `coverage_urgency` here is taken as an already-computed plain `f32`,
/// the same way `authority_match_term` takes `authority_match` and
/// `trigger_match_term` takes `trigger_match`: architecture §3.7 requires
/// the ranking formula to be a "pure function, no I/O beyond the local
/// index," which rules out this module tracking coverage state (which
/// template sections are filled, how much meeting time remains) itself.
/// No coverage-tracking module exists yet in this repo to cite by name --
/// unlike `authority_match`'s and `trigger_match`'s upstream producers --
/// but the same architectural constraint applies regardless of whether that
/// producer has been built yet, so this function is written against the
/// contract rather than a concrete caller.
///
/// Because this term enters the ranking sum with a positive sign and
/// `coverage_urgency` only grows as a section becomes more unfilled and
/// more time-pressured, a more urgent candidate always contributes at least
/// as much to the total score as an otherwise-identical, less urgent one --
/// see `a_more_urgent_candidate_scores_higher` below.
pub fn coverage_urgency_term(coverage_urgency: f32, weight: f32) -> f32 {
    weight * coverage_urgency
}

/// Placeholder magnitude for the `w₂` weight, pending calibration against
/// the replay harness (architecture §9) -- uncalibrated, same caveat
/// attached to every other default weight/threshold in this module.
/// Architecture §3.7 is explicit that weights are configuration, not
/// hardcoded, so this constant is only ever a caller's fallback default,
/// never baked into `coverage_urgency_term` itself.
pub const DEFAULT_COVERAGE_URGENCY_WEIGHT: f32 = 1.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_more_urgent_candidate_scores_higher() {
        let urgent = coverage_urgency_term(1.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        let calm = coverage_urgency_term(0.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        assert!(urgent > calm);
    }

    #[test]
    fn a_partially_urgent_candidate_scores_between_fully_urgent_and_not_urgent() {
        let full = coverage_urgency_term(1.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        let half = coverage_urgency_term(0.5, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        let none = coverage_urgency_term(0.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        assert!(none < half && half < full);
    }

    #[test]
    fn a_zero_weight_makes_the_term_ignore_urgency_entirely() {
        assert_eq!(
            coverage_urgency_term(1.0, 0.0),
            coverage_urgency_term(0.0, 0.0)
        );
    }

    #[test]
    fn the_term_scales_linearly_with_weight() {
        assert_eq!(coverage_urgency_term(1.0, 2.0), 2.0);
        assert_eq!(coverage_urgency_term(0.5, 2.0), 1.0);
    }

    #[test]
    fn the_default_weight_makes_higher_urgency_never_score_lower() {
        let urgent = coverage_urgency_term(1.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        let calm = coverage_urgency_term(0.0, DEFAULT_COVERAGE_URGENCY_WEIGHT);
        assert!(urgent >= calm);
    }
}
