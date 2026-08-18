//! Weighted alignment and scoring (PRD NFR-5.1, NFR-5.7).

use crate::entity::{classify, EngagementVocabulary, EntityClass};

/// Per-category weight applied to an alignment error. Defaults weight the
/// four NFR-5.1 categories at 3x an ordinary word — sourced from the
/// weighting sclite-style scorers commonly use for named entities, not
/// from a PRD-mandated constant. Tune per T9 (architecture) once a labelled
/// reference set exists to validate the multiplier against.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AlignmentWeights {
    pub numeral: f32,
    pub proper_noun: f32,
    pub negation: f32,
    pub engagement_vocabulary: f32,
    pub other: f32,
}

impl Default for AlignmentWeights {
    fn default() -> Self {
        Self {
            numeral: 3.0,
            proper_noun: 3.0,
            negation: 3.0,
            engagement_vocabulary: 3.0,
            other: 1.0,
        }
    }
}

impl AlignmentWeights {
    /// Every category weighted equally — entity-weighted WER under this
    /// reduces to plain WER, which is the backward-compatibility check in
    /// this module's tests.
    pub fn uniform(weight: f32) -> Self {
        Self {
            numeral: weight,
            proper_noun: weight,
            negation: weight,
            engagement_vocabulary: weight,
            other: weight,
        }
    }

    /// A token can match several classes (`Q3` is both a numeral and a
    /// proper noun); take the highest applicable weight rather than
    /// summing, so a multi-class token counts once, not several times.
    fn weight_for(&self, classes: &[EntityClass]) -> f32 {
        classes
            .iter()
            .map(|class| match class {
                EntityClass::Numeral => self.numeral,
                EntityClass::ProperNoun => self.proper_noun,
                EntityClass::Negation => self.negation,
                EntityClass::EngagementVocabulary => self.engagement_vocabulary,
                EntityClass::Other => self.other,
            })
            .fold(f32::MIN, f32::max)
    }
}

/// Result of scoring one reference/hypothesis pair.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UtteranceReport {
    pub weighted_errors: f32,
    pub weighted_reference_len: f32,
    pub substitutions: u32,
    pub deletions: u32,
    pub insertions: u32,
}

impl UtteranceReport {
    /// Entity-weighted WER for this one utterance. Empty reference scores
    /// 0.0 rather than dividing by zero — there is nothing to have gotten
    /// wrong.
    pub fn wer(&self) -> f32 {
        if self.weighted_reference_len == 0.0 {
            0.0
        } else {
            self.weighted_errors / self.weighted_reference_len
        }
    }
}

/// Result of folding a whole run's utterance pairs into one figure.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RunReport {
    pub entity_weighted_wer: f32,
    pub utterances_scored: usize,
    pub weighted_errors: f32,
    pub weighted_reference_len: f32,
}

#[derive(Clone, Copy)]
enum Op {
    Match,
    Sub,
    Del,
    Ins,
}

/// Score one reference/hypothesis pair via minimum-weighted-cost alignment:
/// a Levenshtein-style DP where substituting or deleting a reference token
/// costs that token's entity weight (0 on an exact match), and inserting an
/// unmatched hypothesis token costs that token's own weight. This directly
/// generalises plain WER — [`AlignmentWeights::uniform`]`(1.0)` reduces the
/// weighted total to the ordinary edit-distance count.
pub fn score_utterance<S: AsRef<str>>(
    reference: &[S],
    hypothesis: &[S],
    vocabulary: &EngagementVocabulary,
    weights: &AlignmentWeights,
) -> UtteranceReport {
    let reference: Vec<&str> = reference.iter().map(AsRef::as_ref).collect();
    let hypothesis: Vec<&str> = hypothesis.iter().map(AsRef::as_ref).collect();

    let ref_weight = |i: usize| weights.weight_for(&classify(reference[i], i == 0, vocabulary));
    let hyp_weight = |j: usize| weights.weight_for(&classify(hypothesis[j], j == 0, vocabulary));

    let n = reference.len();
    let m = hypothesis.len();

    let mut cost = vec![vec![0.0f32; m + 1]; n + 1];
    let mut op = vec![vec![Op::Match; m + 1]; n + 1];

    for (i, row) in op.iter_mut().enumerate().skip(1) {
        cost[i][0] = cost[i - 1][0] + ref_weight(i - 1);
        row[0] = Op::Del;
    }
    for j in 1..=m {
        cost[0][j] = cost[0][j - 1] + hyp_weight(j - 1);
        op[0][j] = Op::Ins;
    }

    for i in 1..=n {
        for j in 1..=m {
            let is_match = reference[i - 1] == hypothesis[j - 1];
            let diag = cost[i - 1][j - 1] + if is_match { 0.0 } else { ref_weight(i - 1) };
            let del = cost[i - 1][j] + ref_weight(i - 1);
            let ins = cost[i][j - 1] + hyp_weight(j - 1);

            let mut best = diag;
            let mut best_op = if is_match { Op::Match } else { Op::Sub };
            if del < best {
                best = del;
                best_op = Op::Del;
            }
            if ins < best {
                best = ins;
                best_op = Op::Ins;
            }
            cost[i][j] = best;
            op[i][j] = best_op;
        }
    }

    let mut substitutions = 0u32;
    let mut deletions = 0u32;
    let mut insertions = 0u32;
    let (mut i, mut j) = (n, m);
    while i > 0 || j > 0 {
        match op[i][j] {
            Op::Match => {
                i -= 1;
                j -= 1;
            }
            Op::Sub => {
                substitutions += 1;
                i -= 1;
                j -= 1;
            }
            Op::Del => {
                deletions += 1;
                i -= 1;
            }
            Op::Ins => {
                insertions += 1;
                j -= 1;
            }
        }
    }

    let weighted_reference_len: f32 = (0..n).map(ref_weight).sum();

    UtteranceReport {
        weighted_errors: cost[n][m],
        weighted_reference_len,
        substitutions,
        deletions,
        insertions,
    }
}

/// Fold every reference/hypothesis pair in a run into the single published
/// figure NFR-5.7 asks for. This is corpus-level (total weighted errors
/// over total weighted reference length across the whole run), not an
/// average of per-utterance WERs — a run with one 2-word utterance and one
/// 200-word utterance should not let the short one skew the figure.
/// Partition pairs by language and capture mode before calling this, once
/// per partition, since NFR-5.7 forbids a single global figure.
pub fn score_run<'a, S, I>(
    pairs: I,
    vocabulary: &EngagementVocabulary,
    weights: &AlignmentWeights,
) -> RunReport
where
    S: AsRef<str> + 'a,
    I: IntoIterator<Item = (&'a [S], &'a [S])>,
{
    let mut weighted_errors = 0.0f32;
    let mut weighted_reference_len = 0.0f32;
    let mut utterances_scored = 0usize;

    for (reference, hypothesis) in pairs {
        let report = score_utterance(reference, hypothesis, vocabulary, weights);
        weighted_errors += report.weighted_errors;
        weighted_reference_len += report.weighted_reference_len;
        utterances_scored += 1;
    }

    let entity_weighted_wer = if weighted_reference_len == 0.0 {
        0.0
    } else {
        weighted_errors / weighted_reference_len
    };

    RunReport {
        entity_weighted_wer,
        utterances_scored,
        weighted_errors,
        weighted_reference_len,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(text: &str) -> Vec<String> {
        text.split_whitespace().map(str::to_string).collect()
    }

    #[test]
    fn identical_transcript_scores_zero() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let text = words("the client will not renew in Q3");
        let report = score_utterance(&text, &text, &vocab, &weights);
        assert_eq!(report.wer(), 0.0);
        assert_eq!(report.substitutions, 0);
        assert_eq!(report.deletions, 0);
        assert_eq!(report.insertions, 0);
    }

    #[test]
    fn uniform_weights_reduce_to_plain_wer() {
        // 3 of 3 reference words substituted, no weighting distinction: plain
        // WER of 1.0. This is the backward-compatibility check for the
        // weighted DP — NFR-5.1 adds weighting on top of WER, not instead of it.
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::uniform(1.0);
        let reference = words("the cat sat");
        let hypothesis = words("a dog ran");
        let report = score_utterance(&reference, &hypothesis, &vocab, &weights);
        assert_eq!(report.wer(), 1.0);
        assert_eq!(report.substitutions, 3);
    }

    #[test]
    fn misrecognised_numeral_weighs_more_than_misrecognised_filler_word() {
        // Same shape of error (one substitution out of five words) landing on
        // a numeral vs. an ordinary word: NFR-5.1's entire point is that the
        // numeral case must score worse, since it is what breaks `quantify`.
        // Numbers are already in digit form by the time transcripts reach
        // scoring (FR-2.17 normalises spoken numbers upstream), so the
        // reference/hypothesis here use digits rather than spelled-out words.
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();

        let numeral_reference = words("it will take 15 days");
        let numeral_hypothesis = words("it will take 50 days");
        let numeral_report =
            score_utterance(&numeral_reference, &numeral_hypothesis, &vocab, &weights);

        let filler_reference = words("it will surely take days");
        let filler_hypothesis = words("it will simply take days");
        let filler_report =
            score_utterance(&filler_reference, &filler_hypothesis, &vocab, &weights);

        assert_eq!(numeral_report.substitutions, 1);
        assert_eq!(filler_report.substitutions, 1);
        assert!(
            numeral_report.wer() > filler_report.wer(),
            "numeral substitution WER {} should exceed filler substitution WER {}",
            numeral_report.wer(),
            filler_report.wer()
        );
    }

    #[test]
    fn dropped_negation_weighs_more_than_dropped_filler_word() {
        // A deleted "not" inverts the client's meaning; a deleted "just" does
        // not. Both are one deletion out of the same reference length.
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();

        let negation_reference = words("we will not renew this year");
        let negation_hypothesis = words("we will renew this year");
        let negation_report =
            score_utterance(&negation_reference, &negation_hypothesis, &vocab, &weights);

        let filler_reference = words("we will just renew this year");
        let filler_hypothesis = words("we will renew this year");
        let filler_report =
            score_utterance(&filler_reference, &filler_hypothesis, &vocab, &weights);

        assert_eq!(negation_report.deletions, 1);
        assert_eq!(filler_report.deletions, 1);
        assert!(negation_report.wer() > filler_report.wer());
    }

    #[test]
    fn engagement_vocabulary_error_is_weighted() {
        let vocab = EngagementVocabulary::new(["Snowflake"]);
        let weights = AlignmentWeights::default();

        let reference = words("we migrated off snowflake last quarter");
        let hypothesis = words("we migrated off snowflate last quarter");
        let report = score_utterance(&reference, &hypothesis, &vocab, &weights);

        assert_eq!(report.substitutions, 1);
        assert_eq!(
            report.wer(),
            weights.engagement_vocabulary / report.weighted_reference_len
        );
    }

    #[test]
    fn score_run_is_corpus_level_not_averaged_per_utterance() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::uniform(1.0);

        let short_reference = words("no");
        let short_hypothesis = words("go");
        let long_reference = words("the quick brown fox jumps over the lazy dog again");
        let long_hypothesis = long_reference.clone();

        let pairs: Vec<(&[String], &[String])> = vec![
            (&short_reference[..], &short_hypothesis[..]),
            (&long_reference[..], &long_hypothesis[..]),
        ];
        let run = score_run(pairs, &vocab, &weights);

        // 1 error over 1 + 10 = 11 total weighted reference words, not an
        // average of 1.0 (short utterance) and 0.0 (long utterance).
        assert_eq!(run.utterances_scored, 2);
        assert!((run.entity_weighted_wer - (1.0 / 11.0)).abs() < 1e-6);
    }

    #[test]
    fn empty_reference_scores_zero_rather_than_dividing_by_zero() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let reference: Vec<String> = vec![];
        let hypothesis = words("hello");
        let report = score_utterance(&reference, &hypothesis, &vocab, &weights);
        assert_eq!(report.wer(), 0.0);
    }
}
