//! Reads the ranking formula's `w₁..w₆` weights (architecture §3.7) from
//! environment configuration rather than the hardcoded [`DEFAULT_WEIGHTS`]
//! placeholder, so the replay harness (architecture §9) can tune them per
//! run without recompiling. The harness invokes the shared core as a
//! subprocess (`SubprocessCoreEngine`, `apps/service/.../replay/harness/
//! subprocess_engine.py`) over a fixed stdin/argv contract, so environment
//! variables are the one channel available to vary weights per run without
//! changing that contract.
//!
//! Each weight has its own environment variable and falls back to
//! [`DEFAULT_WEIGHTS`]'s matching field when unset or unparsable -- an
//! invalid override degrades to the placeholder default rather than
//! panicking, the same "malformed input degrades gracefully" contract this
//! crate's other terms use for degenerate inputs (see `priority.rs`'s
//! non-positive-priority handling).

use super::candidate_score::{ScoreWeights, DEFAULT_WEIGHTS};

/// Environment variable read for [`ScoreWeights::trigger_match`].
pub const TRIGGER_MATCH_WEIGHT_ENV: &str = "RANKING_WEIGHT_TRIGGER_MATCH";
/// Environment variable read for [`ScoreWeights::coverage_urgency`].
pub const COVERAGE_URGENCY_WEIGHT_ENV: &str = "RANKING_WEIGHT_COVERAGE_URGENCY";
/// Environment variable read for [`ScoreWeights::authority_match`].
pub const AUTHORITY_MATCH_WEIGHT_ENV: &str = "RANKING_WEIGHT_AUTHORITY_MATCH";
/// Environment variable read for [`ScoreWeights::priority`].
pub const PRIORITY_WEIGHT_ENV: &str = "RANKING_WEIGHT_PRIORITY";
/// Environment variable read for [`ScoreWeights::recency_penalty`].
pub const RECENCY_PENALTY_WEIGHT_ENV: &str = "RANKING_WEIGHT_RECENCY_PENALTY";
/// Environment variable read for [`ScoreWeights::asked_penalty`].
pub const ASKED_PENALTY_WEIGHT_ENV: &str = "RANKING_WEIGHT_ASKED_PENALTY";

/// Parses one weight override, pulled out of [`weights_from_env`] so the
/// fallback-on-missing-or-invalid behaviour has direct unit test coverage
/// without every case needing to mutate process environment. A missing
/// value, an unparsable string, or a non-finite float (`NaN`/`inf`, which
/// would otherwise poison every downstream sum) all degrade to `default`.
fn resolve_weight(raw: Option<&str>, default: f32) -> f32 {
    raw.and_then(|value| value.trim().parse::<f32>().ok())
        .filter(|value| value.is_finite())
        .unwrap_or(default)
}

/// Reads all six weights from environment configuration, falling back to
/// [`DEFAULT_WEIGHTS`] field-by-field for whichever are unset or
/// unparsable -- the "configuration, not hardcoded constants" mechanism
/// architecture §3.7 calls for, in the one form a subprocess-boundary
/// replay harness run can actually set before invoking the core binary.
pub fn weights_from_env() -> ScoreWeights {
    ScoreWeights {
        trigger_match: resolve_weight(
            std::env::var(TRIGGER_MATCH_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.trigger_match,
        ),
        coverage_urgency: resolve_weight(
            std::env::var(COVERAGE_URGENCY_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.coverage_urgency,
        ),
        authority_match: resolve_weight(
            std::env::var(AUTHORITY_MATCH_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.authority_match,
        ),
        priority: resolve_weight(
            std::env::var(PRIORITY_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.priority,
        ),
        recency_penalty: resolve_weight(
            std::env::var(RECENCY_PENALTY_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.recency_penalty,
        ),
        asked_penalty: resolve_weight(
            std::env::var(ASKED_PENALTY_WEIGHT_ENV).ok().as_deref(),
            DEFAULT_WEIGHTS.asked_penalty,
        ),
    }
}

/// Formats the active weight set as a single run-log line -- the
/// acceptance criterion this feature exists to satisfy: "the run log emits
/// the active weight set." Whichever binary entry point owns actually
/// writing the run log (not yet built in this crate -- see `HANDOFF.md`)
/// writes this line verbatim rather than re-deriving its own formatting,
/// so every run's log records precisely the weights that scored it.
pub fn active_weights_log_line(weights: &ScoreWeights) -> String {
    format!(
        "active ranking weights: trigger_match={:.4} coverage_urgency={:.4} authority_match={:.4} priority={:.4} recency_penalty={:.4} asked_penalty={:.4}",
        weights.trigger_match,
        weights.coverage_urgency,
        weights.authority_match,
        weights.priority,
        weights.recency_penalty,
        weights.asked_penalty
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // Environment variables are process-global mutable state, so tests
    // that set/clear them must not interleave with each other across
    // cargo test's threads within this one binary.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_env() {
        for key in [
            TRIGGER_MATCH_WEIGHT_ENV,
            COVERAGE_URGENCY_WEIGHT_ENV,
            AUTHORITY_MATCH_WEIGHT_ENV,
            PRIORITY_WEIGHT_ENV,
            RECENCY_PENALTY_WEIGHT_ENV,
            ASKED_PENALTY_WEIGHT_ENV,
        ] {
            std::env::remove_var(key);
        }
    }

    #[test]
    fn resolve_weight_falls_back_to_default_when_unset() {
        assert_eq!(resolve_weight(None, 1.0), 1.0);
    }

    #[test]
    fn resolve_weight_falls_back_to_default_when_unparsable() {
        assert_eq!(resolve_weight(Some("not-a-number"), 1.0), 1.0);
    }

    #[test]
    fn resolve_weight_falls_back_to_default_for_non_finite_overrides() {
        assert_eq!(resolve_weight(Some("NaN"), 1.0), 1.0);
        assert_eq!(resolve_weight(Some("inf"), 1.0), 1.0);
    }

    #[test]
    fn resolve_weight_reads_a_valid_override() {
        assert_eq!(resolve_weight(Some("2.5"), 1.0), 2.5);
    }

    #[test]
    fn weights_from_env_reads_every_configured_override() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        std::env::set_var(TRIGGER_MATCH_WEIGHT_ENV, "0.4");
        std::env::set_var(COVERAGE_URGENCY_WEIGHT_ENV, "0.3");
        std::env::set_var(AUTHORITY_MATCH_WEIGHT_ENV, "0.2");
        std::env::set_var(PRIORITY_WEIGHT_ENV, "0.1");
        std::env::set_var(RECENCY_PENALTY_WEIGHT_ENV, "0.15");
        std::env::set_var(ASKED_PENALTY_WEIGHT_ENV, "0.05");

        let weights = weights_from_env();
        clear_env();

        assert_eq!(
            weights,
            ScoreWeights {
                trigger_match: 0.4,
                coverage_urgency: 0.3,
                authority_match: 0.2,
                priority: 0.1,
                recency_penalty: 0.15,
                asked_penalty: 0.05,
            }
        );
    }

    #[test]
    fn weights_from_env_falls_back_to_defaults_when_unset() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        assert_eq!(weights_from_env(), DEFAULT_WEIGHTS);
    }

    #[test]
    fn weights_from_env_ignores_an_unparsable_override_for_one_field() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        std::env::set_var(TRIGGER_MATCH_WEIGHT_ENV, "not-a-number");
        std::env::set_var(COVERAGE_URGENCY_WEIGHT_ENV, "0.3");

        let weights = weights_from_env();
        clear_env();

        assert_eq!(weights.trigger_match, DEFAULT_WEIGHTS.trigger_match);
        assert_eq!(weights.coverage_urgency, 0.3);
    }

    #[test]
    fn the_run_log_line_names_every_active_weight() {
        let weights = ScoreWeights {
            trigger_match: 0.4,
            coverage_urgency: 0.3,
            authority_match: 0.2,
            priority: 0.1,
            recency_penalty: 0.15,
            asked_penalty: 0.05,
        };
        let line = active_weights_log_line(&weights);
        assert!(line.contains("0.4000"));
        assert!(line.contains("0.3000"));
        assert!(line.contains("0.2000"));
        assert!(line.contains("0.1000"));
        assert!(line.contains("0.1500"));
        assert!(line.contains("0.0500"));
    }

    #[test]
    fn a_configured_weight_set_reaches_the_run_log_end_to_end() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        std::env::set_var(TRIGGER_MATCH_WEIGHT_ENV, "0.9");
        std::env::set_var(COVERAGE_URGENCY_WEIGHT_ENV, "0.05");
        std::env::set_var(AUTHORITY_MATCH_WEIGHT_ENV, "0.03");
        std::env::set_var(PRIORITY_WEIGHT_ENV, "0.02");
        std::env::set_var(RECENCY_PENALTY_WEIGHT_ENV, "0.04");
        std::env::set_var(ASKED_PENALTY_WEIGHT_ENV, "0.01");

        let weights = weights_from_env();
        let line = active_weights_log_line(&weights);
        clear_env();

        assert_ne!(weights, DEFAULT_WEIGHTS);
        assert!(line.contains("0.9000"));
        assert!(line.contains("0.0500"));
        assert!(line.contains("0.0300"));
        assert!(line.contains("0.0200"));
        assert!(line.contains("0.0400"));
        assert!(line.contains("0.0100"));
    }
}
