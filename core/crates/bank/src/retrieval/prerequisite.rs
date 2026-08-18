//! Filters candidates whose `requires` prerequisites (architecture §3.6's
//! `requires` column, "JSON array of prerequisite candidate ids") aren't
//! satisfied yet -- architecture §3.7: "Candidates whose `requires`
//! prerequisites are unsatisfied are filtered before scoring." This is that
//! filter, run ahead of [`crate::retrieval::retrieve_ranked_candidates`] so
//! an unsatisfied candidate never reaches the cosine scoring pass at all.
//!
//! `apps/service`'s `compiler/tagging/tag_candidates.py` already guarantees,
//! at compile time, that every `requires` id names a real candidate in the
//! same bank and never the candidate's own id -- this module doesn't
//! re-validate that; it only decides, for an already-valid bank, which
//! candidates are answerable right now given which candidate ids are
//! already satisfied.

use std::collections::HashSet;

/// One candidate's id and the prerequisite candidate ids (architecture
/// §3.6's `requires` column) that must already be satisfied before this
/// candidate may be scored -- decoupled from every other field on the row,
/// mirroring [`crate::retrieval::CandidateVector`]'s "only what this stage
/// needs" shape.
#[derive(Debug, Clone, PartialEq)]
pub struct PrerequisiteCandidate {
    pub id: String,
    pub requires: Vec<String>,
}

/// Keep only the candidates in `candidates` whose every `requires` id is
/// present in `satisfied`, preserving input order.
///
/// A candidate with an empty `requires` list has no prerequisite and always
/// passes. A candidate naming even one id not in `satisfied` is dropped
/// entirely -- it emits no candidate, rather than a partial or placeholder
/// one -- so a caller never has to distinguish "filtered out" from "never
/// existed" downstream. `satisfied` is whichever candidate ids the runtime
/// already considers answered (PRD FR-6.7's "Asked it"); this function only
/// applies the filter, it doesn't decide what counts as satisfied.
pub fn filter_unsatisfied_prerequisites(
    candidates: &[PrerequisiteCandidate],
    satisfied: &HashSet<String>,
) -> Vec<PrerequisiteCandidate> {
    candidates
        .iter()
        .filter(|candidate| candidate.requires.iter().all(|id| satisfied.contains(id)))
        .cloned()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(id: &str, requires: &[&str]) -> PrerequisiteCandidate {
        PrerequisiteCandidate {
            id: id.to_string(),
            requires: requires.iter().map(|r| r.to_string()).collect(),
        }
    }

    fn satisfied_set(ids: &[&str]) -> HashSet<String> {
        ids.iter().map(|id| id.to_string()).collect()
    }

    #[test]
    fn a_candidate_with_no_requirements_always_passes() {
        let candidates = vec![candidate("a", &[])];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&[]));
        assert_eq!(result, candidates);
    }

    #[test]
    fn an_unsatisfied_prerequisite_emits_no_candidate() {
        let candidates = vec![candidate("a", &["prereq"])];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&[]));
        assert!(result.is_empty());
    }

    #[test]
    fn a_satisfied_prerequisite_lets_the_candidate_through() {
        let candidates = vec![candidate("a", &["prereq"])];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&["prereq"]));
        assert_eq!(result, candidates);
    }

    #[test]
    fn every_requirement_must_be_satisfied_not_just_one() {
        let candidates = vec![candidate("a", &["prereq-1", "prereq-2"])];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&["prereq-1"]));
        assert!(result.is_empty());
    }

    #[test]
    fn all_requirements_satisfied_lets_the_candidate_through() {
        let candidates = vec![candidate("a", &["prereq-1", "prereq-2"])];
        let result = filter_unsatisfied_prerequisites(
            &candidates,
            &satisfied_set(&["prereq-1", "prereq-2"]),
        );
        assert_eq!(result, candidates);
    }

    #[test]
    fn satisfied_and_unsatisfied_candidates_are_partitioned_independently() {
        let candidates = vec![
            candidate("ready", &["prereq"]),
            candidate("blocked", &["missing"]),
            candidate("no-prereq", &[]),
        ];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&["prereq"]));
        let ids: Vec<&str> = result.iter().map(|c| c.id.as_str()).collect();
        assert_eq!(ids, vec!["ready", "no-prereq"]);
    }

    #[test]
    fn input_order_is_preserved_among_survivors() {
        let candidates = vec![
            candidate("first", &[]),
            candidate("second", &[]),
            candidate("third", &[]),
        ];
        let result = filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&[]));
        let ids: Vec<&str> = result.iter().map(|c| c.id.as_str()).collect();
        assert_eq!(ids, vec!["first", "second", "third"]);
    }

    #[test]
    fn an_empty_candidate_list_emits_an_empty_result() {
        let result = filter_unsatisfied_prerequisites(&[], &satisfied_set(&["anything"]));
        assert!(result.is_empty());
    }

    #[test]
    fn satisfied_ids_irrelevant_to_any_candidate_are_ignored() {
        let candidates = vec![candidate("a", &[])];
        let result =
            filter_unsatisfied_prerequisites(&candidates, &satisfied_set(&["unrelated-id"]));
        assert_eq!(result, candidates);
    }
}
