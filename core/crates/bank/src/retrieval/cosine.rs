/// One candidate's id and its embedding vector (the `candidate.embedding`
/// `BLOB` column, architecture §3.6, decoded to `f32`s) -- decoupled from
/// every other field on the row, since brute-force retrieval only ever
/// needs an id to return and a vector to score against the query.
#[derive(Debug, Clone, PartialEq)]
pub struct CandidateVector {
    pub id: String,
    pub embedding: Vec<f32>,
}

/// One candidate's id and its cosine similarity to the query.
#[derive(Debug, Clone, PartialEq)]
pub struct RankedCandidate {
    pub id: String,
    pub score: f32,
}

/// Rank every candidate in `bank` against `query` by cosine similarity,
/// highest first -- the "ranked candidate list" this feature exists to
/// produce.
///
/// Brute-force and exhaustive over the whole slice, not top-k: architecture
/// §3.6 sizes the compiled bank at ~200 candidates and calls an approximate
/// index "unnecessary complexity" at that scale, so this scans every
/// candidate once rather than maintaining any index structure. A candidate
/// whose embedding has a different dimensionality than `query`, or whose
/// vector is all zeros (cosine is undefined against the zero vector),
/// scores `0.0` rather than panicking or propagating `NaN` -- a malformed
/// row degrades to "ranked last, never surfaced," not a crash on the
/// retrieval hot path.
pub fn retrieve_ranked_candidates(query: &[f32], bank: &[CandidateVector]) -> Vec<RankedCandidate> {
    let mut ranked: Vec<RankedCandidate> = bank
        .iter()
        .map(|candidate| RankedCandidate {
            id: candidate.id.clone(),
            score: cosine_similarity(query, &candidate.embedding),
        })
        .collect();
    ranked.sort_by(|a, b| b.score.total_cmp(&a.score));
    ranked
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() {
        return 0.0;
    }

    let mut dot = 0.0f32;
    let mut norm_a = 0.0f32;
    let mut norm_b = 0.0f32;
    for (x, y) in a.iter().zip(b) {
        dot += x * y;
        norm_a += x * x;
        norm_b += y * y;
    }

    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }

    dot / (norm_a.sqrt() * norm_b.sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(id: &str, embedding: Vec<f32>) -> CandidateVector {
        CandidateVector {
            id: id.to_string(),
            embedding,
        }
    }

    #[test]
    fn every_candidate_in_the_bank_appears_in_the_ranked_list() {
        let bank = vec![
            candidate("a", vec![1.0, 0.0]),
            candidate("b", vec![0.0, 1.0]),
            candidate("c", vec![1.0, 1.0]),
        ];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        assert_eq!(ranked.len(), bank.len());
    }

    #[test]
    fn a_candidate_identical_to_the_query_ranks_first() {
        let bank = vec![
            candidate("orthogonal", vec![0.0, 1.0]),
            candidate("identical", vec![1.0, 0.0]),
            candidate("partial", vec![0.5, 0.5]),
        ];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        assert_eq!(ranked[0].id, "identical");
        assert!((ranked[0].score - 1.0).abs() < 1e-6);
    }

    #[test]
    fn an_orthogonal_candidate_scores_zero() {
        let bank = vec![candidate("orthogonal", vec![0.0, 1.0])];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        assert!((ranked[0].score - 0.0).abs() < 1e-6);
    }

    #[test]
    fn an_opposite_candidate_scores_negative_one() {
        let bank = vec![candidate("opposite", vec![-1.0, 0.0])];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        assert!((ranked[0].score + 1.0).abs() < 1e-6);
    }

    #[test]
    fn results_are_sorted_descending_by_score() {
        let bank = vec![
            candidate("low", vec![0.0, 1.0]),
            candidate("high", vec![1.0, 0.0]),
            candidate("mid", vec![0.7, 0.7]),
        ];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        let scores: Vec<f32> = ranked.iter().map(|r| r.score).collect();
        let mut sorted = scores.clone();
        sorted.sort_by(|a, b| b.total_cmp(a));
        assert_eq!(scores, sorted);
    }

    #[test]
    fn an_empty_bank_emits_an_empty_ranked_list() {
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &[]);
        assert!(ranked.is_empty());
    }

    #[test]
    fn a_zero_vector_candidate_scores_zero_instead_of_nan() {
        let bank = vec![candidate("zero", vec![0.0, 0.0])];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        assert_eq!(ranked[0].score, 0.0);
    }

    #[test]
    fn a_dimension_mismatched_candidate_scores_zero_instead_of_panicking() {
        let bank = vec![candidate("short", vec![1.0])];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0, 0.0], &bank);
        assert_eq!(ranked[0].score, 0.0);
    }

    #[test]
    fn scores_are_invariant_to_vector_magnitude() {
        let bank = vec![
            candidate("unit", vec![1.0, 0.0]),
            candidate("scaled", vec![5.0, 0.0]),
        ];
        let ranked = retrieve_ranked_candidates(&[1.0, 0.0], &bank);
        let unit_score = ranked.iter().find(|r| r.id == "unit").unwrap().score;
        let scaled_score = ranked.iter().find(|r| r.id == "scaled").unwrap().score;
        assert!((unit_score - scaled_score).abs() < 1e-6);
    }

    #[test]
    fn brute_force_scans_the_whole_bank_at_realistic_scale() {
        // Architecture §3.6 sizes the compiled bank at ~200 candidates and
        // calls the retrieval design "insensitive anywhere below a few
        // thousand" -- exercise an order of magnitude above that ceiling to
        // prove the scan (not just the API) handles it, without asserting a
        // literal wall-clock bound in CI.
        let bank: Vec<CandidateVector> = (0..5000)
            .map(|i| candidate(&i.to_string(), vec![i as f32, 1.0]))
            .collect();
        let ranked = retrieve_ranked_candidates(&[0.0, 1.0], &bank);
        assert_eq!(ranked.len(), bank.len());
        assert_eq!(ranked[0].id, "0");
    }
}
