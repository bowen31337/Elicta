//! A single language's curated ambiguity lexicon (PRD section 8.2a: "a
//! separate ambiguity lexicon per language, rebuilt for that language rather
//! than translated from English").
//!
//! [`Lexicon::scan`] takes only the tokens [`super::router::LexiconRouter`]
//! has already grouped as this lexicon's own language — it has no way to see
//! any other token, which is what makes "a token emits matches only from its
//! own language lexicon" true by construction rather than by convention.
//! Matching itself runs on an [`super::ahocorasick::AhoCorasick`] automaton
//! built once per lexicon (PRD FR-5.2): every curated term is found in one
//! left-to-right pass over a token's text, and each occurrence carries its
//! own byte [`LexiconMatch::span`] — "the matched span" FR-5.2 requires the
//! gate to emit on the trigger event, not just which token or which term.

use super::ahocorasick::AhoCorasick;
use super::grouping::PositionedToken;
use std::ops::Range;

/// One matched lexicon entry against one token.
#[derive(Debug, Clone, PartialEq)]
pub struct LexiconMatch {
    /// Index (into the original utterance's token vector) of the token this
    /// match was found in.
    pub token_index: usize,
    /// BCP-47 primary subtag of the lexicon that produced this match — never
    /// a different language than the token's own tag, because a lexicon is
    /// only ever scanned over tokens [`super::router::LexiconRouter`] has
    /// already grouped as that language.
    pub language: String,
    /// The persisted identifier of the specific [`Lexicon`] build that
    /// produced this match (PRD section 8.2a) — e.g. `"en-ambiguity-v1"`.
    /// Distinct from `language`: `language` names which BCP-47 tag a lexicon
    /// is scanned over, `lexicon_id` names *which curated build* did the
    /// scanning, so a lexicon that gets rebuilt or revised over time can
    /// still be told apart from an earlier build registered for the same
    /// language. Copied verbatim from the [`Lexicon`] that ran the scan —
    /// there is no path through [`Lexicon::scan`] that fabricates or omits
    /// it.
    pub lexicon_id: String,
    /// The curated lexicon entry that matched, lower-cased.
    pub term: String,
    /// The exact text the match covers, sliced from the lower-cased token
    /// text at `span` — always a valid slice, since `span` was computed
    /// against that exact lower-cased string. Slicing the token's original,
    /// not-yet-lowered text at the same byte offsets instead would risk a
    /// byte-boundary panic for the rare Unicode code point whose lower-cased
    /// form is a different byte length, so this trades exact original-case
    /// rendering for a guarantee that it never panics on real ASR output.
    pub matched_text: String,
    /// Byte range of the match within the token's own (lower-cased) text —
    /// FR-5.2's "the matched span". Scoped to the token, not the utterance:
    /// `Lexicon`/`AhoCorasick` have no visibility beyond the token slice
    /// they were handed, so turning this into an utterance-wide offset is
    /// the caller's job (see `evaluation::token_span`).
    pub span: Range<usize>,
}

/// A curated set of ambiguity terms for one language (unquantified
/// adjectives, vague quantifiers — FR-5.2), scanned only over tokens already
/// known to belong to `language`.
pub struct Lexicon {
    /// A persisted identifier for this specific curated build (PRD section
    /// 8.2a), e.g. `"en-ambiguity-v1"` — stamped onto every
    /// [`LexiconMatch`] this lexicon produces so a match can always be
    /// traced back to the exact curated lexicon that found it, independent
    /// of `language`.
    pub lexicon_id: String,
    pub language: String,
    terms: Vec<String>,
    automaton: AhoCorasick,
}

impl Lexicon {
    /// `terms` need not be pre-lowered — `Lexicon` normalises case itself so
    /// matching stays case-insensitive regardless of how the lexicon was
    /// authored. `lexicon_id` is opaque to this type — it is never parsed,
    /// only carried onto every resulting `LexiconMatch` — so callers are
    /// free to version it however they curate lexicons (`"en-ambiguity-v1"`,
    /// a content hash, etc).
    pub fn new(
        lexicon_id: impl Into<String>,
        language: impl Into<String>,
        terms: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        let terms: Vec<String> = terms.into_iter().map(|t| t.into().to_lowercase()).collect();
        let automaton = AhoCorasick::new(&terms);
        Lexicon {
            lexicon_id: lexicon_id.into(),
            language: language.into(),
            terms,
            automaton,
        }
    }

    /// Scans every token in `tokens` for every curated term in one
    /// Aho-Corasick pass per token (FR-5.2), tagging each match with this
    /// lexicon's own `language` and `lexicon_id` — never the token's,
    /// though by the time a token reaches here (via
    /// [`super::router::LexiconRouter::run`]) `language` always agrees. A
    /// term appearing more than once in a single token produces one
    /// `LexiconMatch` per occurrence, each with its own span, not one match
    /// for the token as a whole.
    pub fn scan(&self, tokens: &[PositionedToken]) -> Vec<LexiconMatch> {
        let mut matches = Vec::new();
        for positioned in tokens {
            let haystack = positioned.token.text.to_lowercase();
            for (term_index, span) in self.automaton.find_all(&haystack) {
                matches.push(LexiconMatch {
                    token_index: positioned.index,
                    language: self.language.clone(),
                    lexicon_id: self.lexicon_id.clone(),
                    term: self.terms[term_index].clone(),
                    matched_text: haystack[span.clone()].to_string(),
                    span,
                });
            }
        }
        matches
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexicon::grouping::TaggedToken;

    fn positioned(index: usize, text: &str, lang: &str) -> PositionedToken {
        PositionedToken {
            index,
            token: TaggedToken {
                text: text.to_string(),
                confidence: 0.9,
                lang: lang.to_string(),
                lang_confidence: 0.9,
            },
        }
    }

    #[test]
    fn scan_matches_a_curated_term_case_insensitively() {
        let lexicon = Lexicon::new("en-test-v1", "en", ["Several", "a lot"]);
        let tokens = vec![positioned(0, "Several", "en")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].term, "several");
        assert_eq!(matches[0].language, "en");
        assert_eq!(matches[0].token_index, 0);
    }

    #[test]
    fn scan_stamps_every_match_with_the_lexicon_that_produced_it() {
        let lexicon = Lexicon::new("en-ambiguity-v1", "en", ["several"]);
        let tokens = vec![positioned(0, "several", "en")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].lexicon_id, "en-ambiguity-v1");
    }

    #[test]
    fn scan_finds_no_match_when_no_term_appears() {
        let lexicon = Lexicon::new("en-test-v1", "en", ["several"]);
        let tokens = vec![positioned(0, "precisely", "en")];

        assert!(lexicon.scan(&tokens).is_empty());
    }

    #[test]
    fn scan_matches_a_substring_within_a_multi_character_token() {
        // e.g. a Chinese ASR token spanning more than the ambiguous phrase.
        let lexicon = Lexicon::new("zh-test-v1", "zh", ["一些"]);
        let tokens = vec![positioned(0, "有一些问题", "zh")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].term, "一些");
    }

    #[test]
    fn scan_only_sees_the_tokens_it_is_given() {
        // Proves the isolation contract at the `Lexicon` level: it has no
        // access to any token outside the slice it's handed, regardless of
        // that token's own `lang` field.
        let lexicon = Lexicon::new("en-test-v1", "en", ["several"]);
        let tokens = vec![positioned(0, "several", "zh")]; // mistagged on purpose

        let matches = lexicon.scan(&tokens);

        // The lexicon has no way to know this token was mistagged: it
        // scans whatever it's handed and stamps its own language. Routing
        // tokens to the *correct* lexicon is `LexiconRouter`'s job, tested
        // in `router.rs`, not this type's.
        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].language, "en");
    }

    #[test]
    fn scan_reports_the_matched_terms_own_span_within_the_token() {
        let lexicon = Lexicon::new("en-test-v1", "en", ["several"]);
        let tokens = vec![positioned(0, "we need several", "en")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].span, 8..15);
        assert_eq!(matches[0].matched_text, "several");
    }

    #[test]
    fn scan_finds_every_occurrence_of_a_term_repeated_in_one_token() {
        let lexicon = Lexicon::new("en-test-v1", "en", ["some"]);
        let tokens = vec![positioned(0, "some issues, and then some more", "en")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 2);
        assert_eq!(matches[0].span, 0..4);
        assert_eq!(matches[1].span, 22..26);
    }

    #[test]
    fn scan_finds_every_distinct_curated_term_in_one_pass_over_a_token() {
        let lexicon = Lexicon::new("en-test-v1", "en", ["several", "a lot", "some"]);
        let tokens = vec![positioned(
            0,
            "there were several, a lot, and some issues",
            "en",
        )];

        let matches = lexicon.scan(&tokens);

        let terms: Vec<&str> = matches.iter().map(|m| m.term.as_str()).collect();
        assert_eq!(terms, vec!["several", "a lot", "some"]);
    }
}
