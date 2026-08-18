//! Groups ASR output tokens by per-token language tag and routes each group
//! to its own segmenter (architecture §3.5, "Language routing").
//!
//! The trigger gate never receives an utterance-level language — it receives
//! per-token language tags (FR-2.13) — because a code-switched sentence such
//! as "这个 API 的 latency 要求是什么" has no single language, and forcing a
//! choice discards whichever half loses. The gate's pipeline is instead:
//!
//! ```text
//! utterance tokens ──▶ group by language tag
//!                        ├─ zh tokens ──▶ zh segmenter ──▶ zh lexicon
//!                        └─ en tokens ──▶ en tokeniser ──▶ en lexicon
//!                                               │
//!                        merge spans ◀──────────┘
//!                        drop spans below tag-confidence threshold (FR-2.22)
//! ```
//!
//! This module owns the first two boxes: `group by language tag` and the
//! routing that hands each group to its per-language [`segmenter::Segmenter`].
//! Grouping happens *after* transcription, over tags the ASR model has
//! already emitted as a by-product — not the detect-then-route pipeline
//! FR-2.12 prohibits on the audio path (architecture §3.5).
//!
//! Languages without orthographic word boundaries need a segmentation stage
//! before lexicon matching can run at all (FR-2.18): the pipeline is
//! `segment → match`, not `match`, and the segmenter is per-language. This
//! module's job stops at handing each language its own token set; it does
//! not own the segmenters or lexicons themselves (those register against
//! [`segmenter::SegmenterRouter`]). It does own merging spans back into
//! utterance order ([`merge::merge_spans`]): the `index` on
//! [`PositionedToken`] carries what that step needs, and it is what makes
//! the merge possible without re-deriving order from anything else.

pub mod merge;
pub mod segmenter;

use std::collections::HashMap;

pub use merge::merge_spans;
pub use segmenter::{CharSegmenter, Segmenter, SegmenterRouter, Span, WhitespaceSegmenter};

/// A single ASR output token carrying its own per-token language tag
/// (FR-2.13). Mirrors the `lang`/`lang_confidence`/`confidence` fields of
/// the architecture's `Token` (§3.2); kept local rather than depending on
/// that type directly because the ASR adapter module that owns it has not
/// landed in this crate yet. Re-point this at the canonical type once it
/// does — the field set is deliberately identical.
#[derive(Debug, Clone, PartialEq)]
pub struct TaggedToken {
    pub text: String,
    /// Per-word transcription confidence (FR-2.3).
    pub confidence: f32,
    /// BCP-47 language tag for this token specifically, not the utterance.
    pub lang: String,
    /// Confidence in `lang`. Gates the deterministic tier (FR-2.22): a
    /// token below threshold is dropped before it ever reaches a segmenter.
    pub lang_confidence: f32,
}

/// A token plus its position in the original utterance's token vector.
/// Grouping by language interleaves and reorders tokens (a code-switched
/// utterance's English and Chinese tokens are not contiguous runs), so the
/// original index is retained for whoever performs the downstream "merge
/// spans" step back into utterance order.
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
/// whose `lang_confidence` is below `min_tag_confidence` (FR-2.22) — an
/// uncertain language tag means an uncertain lexicon match, and routing it
/// anywhere is an M2 event waiting to happen.
///
/// Groups are returned in first-seen order. Within a group, tokens keep
/// their original utterance order and carry their original index, so a
/// code-switched utterance produces exactly one token set per language
/// actually present in it — not one group per token and not a single
/// utterance-level language decision.
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
/// language for routing purposes. Matches the convention already used by
/// `tags::LanguageTierTable::tier_for`; duplicated locally (rather than
/// imported) because `tags` does not expose it and this module stays
/// self-contained pending crate wiring.
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
        // architecture §3.5's own example: no single language, but exactly
        // two token sets once grouped.
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
        assert_eq!(zh.tokens[0].token.text, "这个");
        assert_eq!(zh.tokens[1].token.text, "的");
    }

    #[test]
    fn tokens_below_tag_confidence_threshold_are_dropped() {
        // FR-2.22: an uncertain language tag must not reach a segmenter.
        let tokens = vec![token("maybe", "en", 0.2), token("sure", "en", 0.95)];

        let groups = group_by_language(&tokens, 0.6);

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].tokens.len(), 1);
        assert_eq!(groups[0].tokens[0].token.text, "sure");
    }

    #[test]
    fn a_language_with_only_low_confidence_tokens_emits_no_group() {
        let tokens = vec![token("低置信度", "zh", 0.1)];

        let groups = group_by_language(&tokens, 0.6);

        assert!(groups.is_empty());
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
    fn monolingual_utterance_still_produces_exactly_one_group() {
        let tokens = vec![token("it", "en", 0.9), token("works", "en", 0.9)];

        let groups = group_by_language(&tokens, 0.6);

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].language, "en");
    }

    #[test]
    fn empty_utterance_produces_no_groups() {
        assert!(group_by_language(&[], 0.6).is_empty());
    }
}
