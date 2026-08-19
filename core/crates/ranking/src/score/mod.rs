pub mod asked_penalty;
pub mod authority_match;
pub mod candidate_score;
pub mod cold_start;
pub mod coverage_urgency;
pub mod priority;
pub mod recency_penalty;
pub mod trigger_match;
pub mod weights_config;

pub use asked_penalty::{asked_penalty_term, DEFAULT_ASKED_PENALTY_WEIGHT};
pub use authority_match::{authority_match_term, DEFAULT_AUTHORITY_MATCH_WEIGHT};
pub use candidate_score::{
    score_candidate, score_candidates, CandidateScore, CandidateScoreInputs, ScoreWeights,
    DEFAULT_WEIGHTS,
};
pub use cold_start::{COLD_START_WEIGHTS, MAX_POSITIVE_SCORE};
pub use coverage_urgency::{coverage_urgency_term, DEFAULT_COVERAGE_URGENCY_WEIGHT};
pub use priority::{priority_term, DEFAULT_PRIORITY_WEIGHT};
pub use recency_penalty::{recency_penalty_term, DEFAULT_RECENCY_PENALTY_WEIGHT};
pub use trigger_match::{trigger_match_term, DEFAULT_TRIGGER_MATCH_WEIGHT};
pub use weights_config::{
    active_weights_log_line, weights_from_env, ASKED_PENALTY_WEIGHT_ENV,
    AUTHORITY_MATCH_WEIGHT_ENV, COVERAGE_URGENCY_WEIGHT_ENV, PRIORITY_WEIGHT_ENV,
    RECENCY_PENALTY_WEIGHT_ENV, TRIGGER_MATCH_WEIGHT_ENV,
};
