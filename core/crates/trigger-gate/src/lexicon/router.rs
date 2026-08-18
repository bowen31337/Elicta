//! Routes each of an utterance's per-language token groups to that
//! language's own registered [`Lexicon`], and only that one (feature 145).
//!
//! This is where the isolation guarantee actually lives: [`LexiconRouter::run`]
//! looks up a group's lexicon by the *group's* language and hands the scan
//! only that group's tokens, so a lexicon literally never receives a token
//! tagged for a different language. A language present in the utterance but
//! with no registered lexicon contributes zero matches rather than falling
//! back to another language's terms — silently reusing, say, the English
//! lexicon for untagged Chinese tokens would defeat section 8.2a's
//! requirement for a lexicon "rebuilt for that language rather than
//! translated from English".

use std::collections::HashMap;

use super::grouping::{group_by_language, TaggedToken};
use super::terms::{Lexicon, LexiconMatch};

/// Holds one [`Lexicon`] per language and dispatches each utterance's
/// tokens to their own tagged language's lexicon.
pub struct LexiconRouter {
    lexicons: HashMap<String, Lexicon>,
}

impl LexiconRouter {
    pub fn new() -> Self {
        LexiconRouter {
            lexicons: HashMap::new(),
        }
    }

    /// Registers `lexicon` for its own `language`, replacing any previously
    /// registered lexicon for that language.
    pub fn register(&mut self, lexicon: Lexicon) {
        self.lexicons.insert(lexicon.language.clone(), lexicon);
    }

    /// Groups `tokens` by language tag (dropping any below
    /// `min_tag_confidence`, per FR-2.22), scans each group with its own
    /// language's registered lexicon, and returns every match ordered by
    /// original token index — restoring utterance order across languages the
    /// same way [`language::segment::merge::merge_spans`] does for spans.
    ///
    /// A group whose language has no registered lexicon contributes no
    /// matches: it is not scanned by any other language's lexicon, and it is
    /// not dropped from consideration silently — it is simply a language
    /// this router has nothing curated for yet.
    pub fn run(&self, tokens: &[TaggedToken], min_tag_confidence: f32) -> Vec<LexiconMatch> {
        let mut matches: Vec<LexiconMatch> = group_by_language(tokens, min_tag_confidence)
            .into_iter()
            .filter_map(|group| {
                self.lexicons
                    .get(&group.language)
                    .map(|lexicon| lexicon.scan(&group.tokens))
            })
            .flatten()
            .collect();

        matches.sort_by_key(|m| m.token_index);
        matches
    }
}

impl Default for LexiconRouter {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn token(text: &str, lang: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    fn router_with_en_and_zh_lexicons() -> LexiconRouter {
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en", ["several", "a lot"]));
        router.register(Lexicon::new("zh", ["一些", "很多"]));
        router
    }

    #[test]
    fn code_switched_utterance_matches_both_languages_neither_half_discarded() {
        // architecture §3.5's own example sentence, extended with an
        // ambiguity term on each side of the code-switch.
        let tokens = vec![
            token("这个", "zh"),
            token("API", "en"),
            token("needs", "en"),
            token("several", "en"),
            token("的", "zh"),
            token("很多", "zh"),
            token("fixes", "en"),
        ];

        let matches = router_with_en_and_zh_lexicons().run(&tokens, 0.6);

        let en_matches: Vec<_> = matches.iter().filter(|m| m.language == "en").collect();
        let zh_matches: Vec<_> = matches.iter().filter(|m| m.language == "zh").collect();
        assert_eq!(
            en_matches.len(),
            1,
            "the English half must not be discarded"
        );
        assert_eq!(
            zh_matches.len(),
            1,
            "the Chinese half must not be discarded"
        );
        assert_eq!(en_matches[0].token_index, 3); // "several"
        assert_eq!(zh_matches[0].token_index, 5); // "很多"
    }

    #[test]
    fn a_token_never_matches_a_different_languages_lexicon() {
        // Both lexicons contain the exact same literal term. A token tagged
        // "en" must produce only an "en" match, never a "zh" one too, even
        // though the zh lexicon "would" match the same text if it were ever
        // run over this token.
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en", ["many"]));
        router.register(Lexicon::new("zh", ["many"])); // contrived cross-language collision

        let tokens = vec![token("many", "en")];
        let matches = router.run(&tokens, 0.6);

        assert_eq!(matches.len(), 1, "must not double-match across languages");
        assert_eq!(matches[0].language, "en");
    }

    #[test]
    fn language_with_no_registered_lexicon_emits_no_matches_and_does_not_fall_back() {
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en", ["several"])); // no "fr" lexicon registered

        let tokens = vec![token("plusieurs", "fr"), token("several", "en")];
        let matches = router.run(&tokens, 0.6);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].language, "en");
    }

    #[test]
    fn tokens_below_language_confidence_threshold_are_never_scanned() {
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en", ["several"]));

        let tokens = vec![TaggedToken {
            text: "several".to_string(),
            confidence: 0.9,
            lang: "en".to_string(),
            lang_confidence: 0.2, // below threshold
        }];

        assert!(router.run(&tokens, 0.6).is_empty());
    }

    #[test]
    fn matches_are_ordered_by_original_utterance_token_index_across_languages() {
        let tokens = vec![
            token("很多", "zh"),
            token("several", "en"),
            token("一些", "zh"),
        ];

        let matches = router_with_en_and_zh_lexicons().run(&tokens, 0.6);

        let indices: Vec<usize> = matches.iter().map(|m| m.token_index).collect();
        assert_eq!(indices, vec![0, 1, 2]);
    }

    #[test]
    fn monolingual_utterance_only_uses_its_own_lexicon() {
        let tokens = vec![token("several", "en"), token("items", "en")];
        let matches = router_with_en_and_zh_lexicons().run(&tokens, 0.6);

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].language, "en");
    }

    #[test]
    fn empty_utterance_emits_no_matches() {
        assert!(router_with_en_and_zh_lexicons().run(&[], 0.6).is_empty());
    }
}
