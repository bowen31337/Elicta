//! Entity classification for entity-weighted WER (PRD NFR-5.1).
//!
//! These are scoring-time heuristics over plain text, not the ASR pipeline's
//! own tagging (that lives on `Token` per architecture §3.2 — `lang`,
//! `confidence` — and carries no entity/POS information). A reference
//! transcript in an eval set is just words, so classification here has to
//! work from text alone. Each heuristic documents its known false
//! positive/negative shape rather than pretending to be exact.

use std::collections::HashSet;

/// Which weighted category a scored token belongs to. NFR-5.1 names four
/// categories explicitly; anything else is `Other` and carries the
/// baseline weight. A token can match more than one (`Q3` is a numeral and
/// may also be engagement vocabulary) — [`classify`] returns every match.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EntityClass {
    Numeral,
    ProperNoun,
    Negation,
    EngagementVocabulary,
    Other,
}

/// Engagement-scoped vocabulary (PRD FR-2.9): client system names, product
/// names, and internal acronyms sourced from the context pack. The same
/// list used for keyterm prompting is the input here — it is precisely the
/// vocabulary a misrecognition turns into a spurious novel-entity trigger.
/// Membership is case-insensitive since ASR casing is not reliable enough
/// to gate on.
#[derive(Debug, Clone, Default)]
pub struct EngagementVocabulary {
    terms: HashSet<String>,
}

impl EngagementVocabulary {
    pub fn new(terms: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Self {
            terms: terms.into_iter().map(|t| t.into().to_lowercase()).collect(),
        }
    }

    pub fn contains(&self, token: &str) -> bool {
        self.terms.contains(&token.to_lowercase())
    }
}

const ENGLISH_NEGATIONS: &[&str] = &[
    "not",
    "no",
    "never",
    "none",
    "nothing",
    "nobody",
    "nowhere",
    "neither",
    "nor",
    "cannot",
    "can't",
    "won't",
    "don't",
    "doesn't",
    "didn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "haven't",
    "hasn't",
    "hadn't",
    "shouldn't",
    "wouldn't",
    "couldn't",
    "n't",
];

// Mandarin negation particles (Tier 1 code-switching, PRD §8.2a).
const MANDARIN_NEGATIONS: &[&str] = &["不", "没", "没有", "别", "无", "非", "未"];

fn is_negation(token: &str) -> bool {
    let lower = token.to_lowercase();
    ENGLISH_NEGATIONS.contains(&lower.as_str()) || MANDARIN_NEGATIONS.contains(&token)
}

// Chinese numeral characters, including magnitude markers (架构 §14.1 /
// FR-2.17's 万/亿 grouping problem lives one layer up in `language::numerals`;
// this only needs to recognise that a run of these characters is numeric).
const CHINESE_NUMERAL_CHARS: &str = "零〇一二三四五六七八九十百千万亿两";

fn is_numeral(token: &str) -> bool {
    if token.is_empty() {
        return false;
    }
    let has_ascii_digit = token.chars().any(|c| c.is_ascii_digit());
    let all_chinese_numeral_chars = token.chars().all(|c| CHINESE_NUMERAL_CHARS.contains(c));
    has_ascii_digit || all_chinese_numeral_chars
}

/// Capitalised and not sentence-initial, or an all-caps acronym (`API`,
/// `AWS`) regardless of position — sentence-initial capitalisation alone is
/// English orthographic convention, not evidence of a proper noun. Known
/// false positive: a capitalised pronoun (`I`) mid-sentence scores as a
/// proper noun; known false negative: lower-cased proper nouns from
/// case-insensitive ASR output are invisible to this heuristic.
fn is_proper_noun(token: &str, is_sentence_start: bool) -> bool {
    let mut chars = token.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_uppercase() {
        return false;
    }
    let rest: Vec<char> = chars.collect();
    let is_all_caps_acronym =
        !rest.is_empty() && rest.iter().all(|c| c.is_uppercase() || c.is_ascii_digit());
    is_all_caps_acronym || !is_sentence_start
}

/// Classify `token` at a given position in its utterance (`is_sentence_start`
/// disambiguates ordinary capitalisation from a proper noun) against the
/// engagement's vocabulary. Returns every matching class, or `[Other]` if
/// none match.
pub fn classify(
    token: &str,
    is_sentence_start: bool,
    vocabulary: &EngagementVocabulary,
) -> Vec<EntityClass> {
    let mut classes = Vec::new();
    if vocabulary.contains(token) {
        classes.push(EntityClass::EngagementVocabulary);
    }
    if is_numeral(token) {
        classes.push(EntityClass::Numeral);
    }
    if is_negation(token) {
        classes.push(EntityClass::Negation);
    }
    if is_proper_noun(token, is_sentence_start) {
        classes.push(EntityClass::ProperNoun);
    }
    if classes.is_empty() {
        classes.push(EntityClass::Other);
    }
    classes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_word_classifies_as_other() {
        let vocab = EngagementVocabulary::default();
        assert_eq!(classify("the", false, &vocab), vec![EntityClass::Other]);
    }

    #[test]
    fn ascii_digit_token_is_a_numeral() {
        let vocab = EngagementVocabulary::default();
        assert_eq!(classify("350", false, &vocab), vec![EntityClass::Numeral]);
    }

    #[test]
    fn chinese_numeral_run_is_a_numeral() {
        let vocab = EngagementVocabulary::default();
        assert_eq!(
            classify("三百五十万", false, &vocab),
            vec![EntityClass::Numeral]
        );
    }

    #[test]
    fn contraction_negation_is_recognised() {
        let vocab = EngagementVocabulary::default();
        assert!(classify("don't", false, &vocab).contains(&EntityClass::Negation));
    }

    #[test]
    fn mandarin_negation_particle_is_recognised() {
        let vocab = EngagementVocabulary::default();
        assert!(classify("没有", false, &vocab).contains(&EntityClass::Negation));
    }

    #[test]
    fn sentence_initial_capital_is_not_a_proper_noun() {
        let vocab = EngagementVocabulary::default();
        assert!(!classify("The", true, &vocab).contains(&EntityClass::ProperNoun));
    }

    #[test]
    fn mid_sentence_capital_is_a_proper_noun() {
        let vocab = EngagementVocabulary::default();
        assert!(classify("Salesforce", false, &vocab).contains(&EntityClass::ProperNoun));
    }

    #[test]
    fn sentence_initial_acronym_is_still_a_proper_noun() {
        let vocab = EngagementVocabulary::default();
        assert!(classify("API", true, &vocab).contains(&EntityClass::ProperNoun));
    }

    #[test]
    fn engagement_vocabulary_match_is_case_insensitive() {
        let vocab = EngagementVocabulary::new(["Snowflake"]);
        assert!(classify("snowflake", false, &vocab).contains(&EntityClass::EngagementVocabulary));
    }

    #[test]
    fn token_can_match_multiple_classes() {
        let vocab = EngagementVocabulary::new(["Q3"]);
        let classes = classify("Q3", false, &vocab);
        assert!(classes.contains(&EntityClass::EngagementVocabulary));
        assert!(classes.contains(&EntityClass::Numeral));
        assert!(classes.contains(&EntityClass::ProperNoun));
    }
}
