//! Merges the per-language spans produced by
//! [`super::segmenter::SegmenterRouter::route`] back into a single ordered
//! span list per utterance — the "merge spans" box in the architecture §3.5
//! pipeline diagram (see `segment`'s module doc).
//!
//! Grouping by language ([`super::group_by_language`]) interleaves and
//! reorders an utterance's tokens: a code-switched sentence's English and
//! Chinese runs are not contiguous once split into per-language
//! [`super::LanguageGroup`]s, so segmenting each group independently produces
//! spans whose relative order is only meaningful *within* their own group,
//! not across the utterance. Every [`super::segmenter::Span`] keeps the
//! original token index (`start_index`/`end_index`) it was built from
//! precisely so this step can restore utterance order without re-deriving it
//! from anything else — this module is where that index finally gets used.

use super::segmenter::Span;

/// Merges spans from every language group's segmentation output back into
/// the order their source tokens held in the original utterance.
///
/// `routed` is the `(language, spans)` pairs [`super::segmenter::SegmenterRouter::route`]
/// returns for one utterance; this always emits exactly one flat, ordered
/// `Vec<Span>` for it — one merged span list per utterance, never per
/// language and never split across calls.
///
/// Spans are ordered by `start_index`, then `end_index`, matching the
/// original token sequence position-for-position regardless of which
/// language group produced them. Spans sharing a `start_index` (e.g.
/// multiple character spans a [`super::segmenter::CharSegmenter`] split from
/// one token) keep the relative order their segmenter produced them in — the
/// sort is stable, so same-token spans are never reordered against each
/// other.
pub fn merge_spans(routed: Vec<(String, Vec<Span>)>) -> Vec<Span> {
    let mut spans: Vec<Span> = routed.into_iter().flat_map(|(_, spans)| spans).collect();
    spans.sort_by_key(|span| (span.start_index, span.end_index));
    spans
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::segment::segmenter::{
        CharSegmenter, Segmenter, SegmenterRouter, WhitespaceSegmenter,
    };
    use crate::segment::TaggedToken;

    fn token(text: &str, lang: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    #[test]
    fn code_switched_utterance_merges_into_one_utterance_ordered_span_list() {
        // architecture §3.5's own example: "这个 API 的 latency 要求是什么".
        let tokens = vec![
            token("这个", "zh"),
            token("API", "en"),
            token("的", "zh"),
            token("latency", "en"),
            token("要求是什么", "zh"),
        ];

        let mut router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        router.register("zh", Box::new(CharSegmenter));

        let routed = router.route(&tokens, 0.6);
        let merged = merge_spans(routed);

        // one flat list, restoring the original token order across languages
        let start_indices: Vec<usize> = merged.iter().map(|s| s.start_index).collect();
        let mut sorted = start_indices.clone();
        sorted.sort_unstable();
        assert_eq!(
            start_indices, sorted,
            "spans must be non-decreasing by original token index"
        );

        assert_eq!(merged.first().unwrap().start_index, 0); // 这个
        assert_eq!(merged.last().unwrap().start_index, 4); // 要求是什么
    }

    #[test]
    fn same_token_spans_keep_their_segmenter_order_on_ties() {
        let g = super::super::LanguageGroup {
            language: "zh".to_string(),
            tokens: vec![super::super::PositionedToken {
                index: 0,
                token: token("你好", "zh"),
            }],
        };
        let spans = CharSegmenter.segment(&g);
        let merged = merge_spans(vec![("zh".to_string(), spans)]);

        assert_eq!(merged.len(), 2);
        assert_eq!(merged[0].text, "你");
        assert_eq!(merged[1].text, "好");
    }

    #[test]
    fn single_language_utterance_merges_to_its_own_order_unchanged() {
        let tokens = vec![token("it", "en"), token("works", "en")];
        let router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        let merged = merge_spans(router.route(&tokens, 0.6));

        assert_eq!(merged.len(), 2);
        assert_eq!(merged[0].text, "it");
        assert_eq!(merged[1].text, "works");
    }

    #[test]
    fn empty_utterance_merges_to_an_empty_span_list() {
        assert!(merge_spans(Vec::new()).is_empty());
    }

    #[test]
    fn route_merged_matches_route_then_merge_spans() {
        let tokens = vec![token("你好", "zh"), token("world", "en")];
        let mut router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        router.register("zh", Box::new(CharSegmenter));

        let via_wrapper = router.route_merged(&tokens, 0.6);
        let via_manual = merge_spans(router.route(&tokens, 0.6));

        assert_eq!(via_wrapper, via_manual);
    }
}
