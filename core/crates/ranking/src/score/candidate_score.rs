use super::authority_match::authority_match_term;
use super::coverage_urgency::coverage_urgency_term;
use super::priority::priority_term;
use super::trigger_match::trigger_match_term;

/// The four already-computed per-candidate values this feature scores --
/// architecture §3.7's ranking formula minus the `recency_penalty` and
/// `asked_penalty` terms, which are separate, not-yet-built concerns (no
/// module in this repo tracks recently-surfaced nudges or "Asked it" taps
/// yet). Every field here is a plain scalar rather than the richer type it
/// derives from -- `trigger_match` is a cosine similarity from
/// `core/crates/bank`'s `retrieval::cosine::RankedCandidate::score`,
/// `authority_match` is `compute_candidate_authority_match`'s output,
/// `priority` is the candidate's raw stored `priority` column -- matching
/// every individual term function's own "pure function, no I/O" contract
/// (architecture §3.7).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CandidateScoreInputs {
    pub trigger_match: f32,
    pub coverage_urgency: f32,
    pub authority_match: f32,
    pub priority: i64,
}

/// The `w₁..w₄` weights this feature's four terms take, mirroring
/// architecture §3.7's "weights are configuration, tuned against the
/// replay harness (§9), not hardcoded." A caller assembling live weights
/// reads them from wherever that configuration lives; [`DEFAULT_WEIGHTS`]
/// exists only as an uncalibrated fallback.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScoreWeights {
    pub trigger_match: f32,
    pub coverage_urgency: f32,
    pub authority_match: f32,
    pub priority: f32,
}

/// Uncalibrated placeholder weights, one per term's own
/// `DEFAULT_*_WEIGHT` constant -- see each term module for why weight
/// calibration is out of scope until the replay harness (architecture §9)
/// exists. A caller assembling *live* weights should read
/// [`super::weights_config::weights_from_env`] instead of this constant --
/// that function reads each field from environment configuration, falling
/// back to this constant's matching field only when no override is set.
pub const DEFAULT_WEIGHTS: ScoreWeights = ScoreWeights {
    trigger_match: super::trigger_match::DEFAULT_TRIGGER_MATCH_WEIGHT,
    coverage_urgency: super::coverage_urgency::DEFAULT_COVERAGE_URGENCY_WEIGHT,
    authority_match: super::authority_match::DEFAULT_AUTHORITY_MATCH_WEIGHT,
    priority: super::priority::DEFAULT_PRIORITY_WEIGHT,
};

/// One candidate's id and its total score.
#[derive(Debug, Clone, PartialEq)]
pub struct CandidateScore {
    pub id: String,
    pub score: f32,
}

/// Sums a single candidate's four terms into its total score -- the
/// `w₁·trigger_match + w₂·coverage_urgency + w₃·authority_match +
/// w₄·priority` slice of architecture §3.7's formula this feature covers.
/// Each term is computed by its own already-tested function; this function
/// only adds them, so a bug in any one term's shape (sign, scaling,
/// degenerate-input handling) is caught by that term's own tests rather
/// than needing to be re-proven here.
pub fn score_candidate(inputs: &CandidateScoreInputs, weights: &ScoreWeights) -> f32 {
    trigger_match_term(inputs.trigger_match, weights.trigger_match)
        + coverage_urgency_term(inputs.coverage_urgency, weights.coverage_urgency)
        + authority_match_term(inputs.authority_match, weights.authority_match)
        + priority_term(inputs.priority, weights.priority)
}

/// Scores every candidate in `candidates` and returns one [`CandidateScore`]
/// per input, in the same order -- the acceptance criterion this feature
/// exists to satisfy: "every candidate emits a score." Unlike
/// `retrieval::cosine::retrieve_ranked_candidates`, this does not sort the
/// result; selecting a winner from these scores is a separate, downstream
/// concern this function doesn't decide.
pub fn score_candidates(
    candidates: &[(String, CandidateScoreInputs)],
    weights: &ScoreWeights,
) -> Vec<CandidateScore> {
    candidates
        .iter()
        .map(|(id, inputs)| CandidateScore {
            id: id.clone(),
            score: score_candidate(inputs, weights),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inputs(
        trigger_match: f32,
        coverage_urgency: f32,
        authority_match: f32,
        priority: i64,
    ) -> CandidateScoreInputs {
        CandidateScoreInputs {
            trigger_match,
            coverage_urgency,
            authority_match,
            priority,
        }
    }

    #[test]
    fn every_candidate_in_the_input_emits_a_score() {
        let candidates = vec![
            ("a".to_string(), inputs(0.5, 0.5, 0.5, 1)),
            ("b".to_string(), inputs(0.1, 0.1, 0.1, 5)),
            ("c".to_string(), inputs(0.9, 0.9, 0.9, 2)),
        ];
        let scores = score_candidates(&candidates, &DEFAULT_WEIGHTS);
        assert_eq!(scores.len(), candidates.len());
    }

    #[test]
    fn scores_preserve_input_order_and_id() {
        let candidates = vec![
            ("first".to_string(), inputs(1.0, 0.0, 0.0, 1)),
            ("second".to_string(), inputs(0.0, 1.0, 0.0, 1)),
        ];
        let scores = score_candidates(&candidates, &DEFAULT_WEIGHTS);
        assert_eq!(scores[0].id, "first");
        assert_eq!(scores[1].id, "second");
    }

    #[test]
    fn an_empty_candidate_list_emits_an_empty_score_list() {
        let scores = score_candidates(&[], &DEFAULT_WEIGHTS);
        assert!(scores.is_empty());
    }

    #[test]
    fn the_total_score_is_the_sum_of_all_four_terms() {
        let weights = ScoreWeights {
            trigger_match: 1.0,
            coverage_urgency: 1.0,
            authority_match: 1.0,
            priority: 1.0,
        };
        // trigger_match_term = 0.5, coverage_urgency_term = 0.25,
        // authority_match_term = 1.0, priority_term = 1.0 / 2 = 0.5
        let total = score_candidate(&inputs(0.5, 0.25, 1.0, 2), &weights);
        assert!((total - 2.25).abs() < 1e-6);
    }

    #[test]
    fn a_fully_matched_candidate_scores_higher_than_a_wholly_unmatched_one() {
        let weights = DEFAULT_WEIGHTS;
        let strong = score_candidate(&inputs(1.0, 1.0, 1.0, 1), &weights);
        let weak = score_candidate(&inputs(0.0, 0.0, 0.0, 1_000_000), &weights);
        assert!(strong > weak);
    }

    #[test]
    fn zeroing_one_term_weight_leaves_the_others_contribution_untouched() {
        let all_weighted = ScoreWeights {
            trigger_match: 1.0,
            coverage_urgency: 1.0,
            authority_match: 1.0,
            priority: 1.0,
        };
        let trigger_zeroed = ScoreWeights {
            trigger_match: 0.0,
            ..all_weighted
        };
        let candidate = inputs(0.7, 0.3, 0.6, 4);
        let difference = score_candidate(&candidate, &all_weighted)
            - score_candidate(&candidate, &trigger_zeroed);
        assert!((difference - 0.7).abs() < 1e-6);
    }
}
