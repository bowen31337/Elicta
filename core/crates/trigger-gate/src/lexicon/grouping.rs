//! Groups an utterance's tokens by per-token language tag, so a per-language
//! lexicon can be scanned over exactly its own tokens and nothing else.
//!
//! Mirrors `language::segment`'s `TaggedToken`/`PositionedToken`/
//! `LanguageGroup`/`group_by_language` field-for-field (see this directory's
//! `mod.rs` for why this is a local copy rather than a shared import).

use std::collections::HashMap;

/// A single ASR output token carrying its own per-token language tag
/// (FR-2.13). A code-switched utterance has no single language, so the tag
/// lives on the token, not the utterance.
#[derive(Debug, Clone, PartialEq)]
pub struct TaggedToken {
    pub text: String,
    /// Per-word transcription confidence (FR-2.3).
    pub confidence: f32,
    /// BCP-47 language tag for this token specifically, not the utterance.
    pub lang: String,
    /// Confidence in `lang`. A token below threshold is dropped before it
    /// ever reaches a lexicon (FR-2.22) — an uncertain language tag means an
    /// uncertain lexicon choice.
    pub lang_confidence: f32,
}

/// A token plus its position in the original utterance's token vector.
/// Grouping by language interleaves and reorders tokens, so the original
/// index is retained for restoring utterance order once each group's
/// lexicon has produced its matches.
#[derive(Debug, Clone, PartialEq)]
pub struct PositionedToken {
    pub index: usize,
    pub token: TaggedToken,
}

/// One language's token set, in original utterance order.
#[derive(Debug, Clone, PartialEq)]
pub struct LanguageGroup {
    /// BCP-47 primary subtag, e.g. `"en"` or `"zh"`.
    pub language: String,
    pub tokens: Vec<PositionedToken>,
}

/// Groups `tokens` by BCP-47 primary language subtag, dropping any token
/// whose `lang_confidence` is below `min_tag_confidence` (FR-2.22).
///
/// Groups are returned in first-seen order. Within a group, tokens keep
/// their original utterance order and index, so a code-switched utterance
/// produces exactly one token set per language actually present in it — the
/// set [`super::router::LexiconRouter::run`] scans with that language's own
/// lexicon, and only that one.
pub fn group_by_language(tokens: &[TaggedToken], min_tag_confidence: f32) -> Vec<LanguageGroup> {
    let mut order: Vec<String> = Vec::new();
    let mut groups: HashMap<String, Vec<PositionedToken>> = HashMap::new();

    for (index, token) in tokens.iter().enumerate() {
        if token.lang_confidence < min_tag_confidence {
            continue;
        }

        let language = primary_subtag(&token.lang);
        groups.entry(language.clone()).or_insert_with(|| {
            order.push(language.clone());
            Vec::new()
        });
        groups
            .get_mut(&language)
            .expect("just inserted above")
            .push(PositionedToken {
                index,
                token: token.clone(),
            });
    }

    order
        .into_iter()
        .map(|language| {
            let tokens = groups.remove(&language).unwrap_or_default();
            LanguageGroup { language, tokens }
        })
        .collect()
}

/// BCP-47 tags group on their primary subtag: "en-US" and "en" are the same
/// language for lexicon-routing purposes.
fn primary_subtag(language: &str) -> String {
    language
        .split(['-', '_'])
        .next()
        .unwrap_or(language)
        .to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn token(text: &str, lang: &str, lang_confidence: f32) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.95,
            lang: lang.to_string(),
            lang_confidence,
        }
    }

    #[test]
    fn code_switched_utterance_produces_one_group_per_language_present() {
        let tokens = vec![
            token("这个", "zh", 0.9),
            token("API", "en", 0.92),
            token("的", "zh", 0.9),
            token("latency", "en", 0.9),
            token("要求", "zh", 0.88),
            token("是什么", "zh", 0.9),
        ];

        let groups = group_by_language(&tokens, 0.6);

        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].language, "zh");
        assert_eq!(groups[1].language, "en");
        assert_eq!(groups[0].tokens.len(), 4);
        assert_eq!(groups[1].tokens.len(), 2);
    }

    #[test]
    fn groups_preserve_original_utterance_order_and_index() {
        let tokens = vec![
            token("这个", "zh", 0.9),
            token("API", "en", 0.9),
            token("的", "zh", 0.9),
        ];

        let groups = group_by_language(&tokens, 0.6);

        let zh = groups.iter().find(|g| g.language == "zh").unwrap();
        assert_eq!(zh.tokens[0].index, 0);
        assert_eq!(zh.tokens[1].index, 2);
    }

    #[test]
    fn tokens_below_tag_confidence_threshold_are_dropped() {
        let tokens = vec![token("maybe", "en", 0.2), token("sure", "en", 0.95)];

        let groups = group_by_language(&tokens, 0.6);

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].tokens.len(), 1);
        assert_eq!(groups[0].tokens[0].token.text, "sure");
    }

    #[test]
    fn bcp47_region_and_script_subtags_collapse_to_the_same_group() {
        let tokens = vec![
            token("hello", "en-US", 0.9),
            token("mate", "en-GB", 0.9),
            token("你好", "zh-Hans", 0.9),
        ];

        let groups = group_by_language(&tokens, 0.6);

        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].language, "en");
        assert_eq!(groups[0].tokens.len(), 2);
        assert_eq!(groups[1].language, "zh");
    }

    #[test]
    fn empty_utterance_produces_no_groups() {
        assert!(group_by_language(&[], 0.6).is_empty());
    }
}
