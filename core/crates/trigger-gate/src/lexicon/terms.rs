//! A single language's curated ambiguity lexicon (PRD section 8.2a: "a
//! separate ambiguity lexicon per language, rebuilt for that language rather
//! than translated from English").
//!
//! [`Lexicon::scan`] takes only the tokens [`super::router::LexiconRouter`]
//! has already grouped as this lexicon's own language — it has no way to see
//! any other token, which is what makes "a token emits matches only from its
//! own language lexicon" true by construction rather than by convention.
//! Matching itself is a plain case-insensitive substring scan; the
//! Aho-Corasick engine (FR-5.2) is a separate feature's performance
//! optimisation over the same contract and can replace this scan without
//! changing [`LexiconMatch`]'s shape.

use super::grouping::PositionedToken;

/// One matched lexicon entry against one token.
#[derive(Debug, Clone, PartialEq)]
pub struct LexiconMatch {
    /// Index (into the original utterance's token vector) of the token this
    /// match was found in.
    pub token_index: usize,
    /// BCP-47 primary subtag of the lexicon that produced this match — never
    /// a different language than the token's own tag, because a lexicon is
    /// only ever scanned over tokens [`super::router::LexiconRouter`] has
    /// already grouped as that language (section 8.2a's "lexicon
    /// identifier").
    pub language: String,
    /// The curated lexicon entry that matched, lower-cased.
    pub term: String,
    /// The token text the match was found in, verbatim.
    pub matched_text: String,
}

/// A curated set of ambiguity terms for one language (unquantified
/// adjectives, vague quantifiers — FR-5.2), scanned only over tokens already
/// known to belong to `language`.
pub struct Lexicon {
    pub language: String,
    terms: Vec<String>,
}

impl Lexicon {
    /// `terms` need not be pre-lowered — `Lexicon` normalises case itself so
    /// matching stays case-insensitive regardless of how the lexicon was
    /// authored.
    pub fn new(
        language: impl Into<String>,
        terms: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        Lexicon {
            language: language.into(),
            terms: terms.into_iter().map(|t| t.into().to_lowercase()).collect(),
        }
    }

    /// Scans every token in `tokens` for every curated term, tagging each
    /// match with this lexicon's own `language` — never the token's, though
    /// by the time a token reaches here (via
    /// [`super::router::LexiconRouter::run`]) the two always agree.
    pub fn scan(&self, tokens: &[PositionedToken]) -> Vec<LexiconMatch> {
        let mut matches = Vec::new();
        for positioned in tokens {
            let haystack = positioned.token.text.to_lowercase();
            for term in &self.terms {
                if haystack.contains(term.as_str()) {
                    matches.push(LexiconMatch {
                        token_index: positioned.index,
                        language: self.language.clone(),
                        term: term.clone(),
                        matched_text: positioned.token.text.clone(),
                    });
                }
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
        let lexicon = Lexicon::new("en", ["Several", "a lot"]);
        let tokens = vec![positioned(0, "Several", "en")];

        let matches = lexicon.scan(&tokens);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].term, "several");
        assert_eq!(matches[0].language, "en");
        assert_eq!(matches[0].token_index, 0);
    }

    #[test]
    fn scan_finds_no_match_when_no_term_appears() {
        let lexicon = Lexicon::new("en", ["several"]);
        let tokens = vec![positioned(0, "precisely", "en")];

        assert!(lexicon.scan(&tokens).is_empty());
    }

    #[test]
    fn scan_matches_a_substring_within_a_multi_character_token() {
        // e.g. a Chinese ASR token spanning more than the ambiguous phrase.
        let lexicon = Lexicon::new("zh", ["一些"]);
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
        let lexicon = Lexicon::new("en", ["several"]);
        let tokens = vec![positioned(0, "several", "zh")]; // mistagged on purpose

        let matches = lexicon.scan(&tokens);

        // The lexicon has no way to know this token was mistagged: it
        // scans whatever it's handed and stamps its own language. Routing
        // tokens to the *correct* lexicon is `LexiconRouter`'s job, tested
        // in `router.rs`, not this type's.
        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].language, "en");
    }
}
