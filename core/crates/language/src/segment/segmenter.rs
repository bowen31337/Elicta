//! Per-language segmenters and the router that dispatches a
//! [`super::LanguageGroup`] to the right one (architecture §3.5).
//!
//! Space-delimited languages arrive from the ASR already word-segmented —
//! each [`super::TaggedToken`] is a lexicon-matchable unit on its own.
//! Languages without orthographic word boundaries are not: the ASR emits
//! runs of characters as a single token, and lexicon matching cannot run
//! against an unsegmented run (FR-2.18). "The pipeline is `segment → match`,
//! not `match`, and the segmenter is per-language" (architecture §3.5).

use super::LanguageGroup;

/// A lexicon-matchable unit produced by a [`Segmenter`], with enough of the
/// originating tokens' provenance to support span-confidence gating
/// (NFR-5.6) and reassembly back into utterance order downstream.
#[derive(Debug, Clone, PartialEq)]
pub struct Span {
    pub text: String,
    /// Index (into the original utterance's token vector) of the first
    /// token this span was built from.
    pub start_index: usize,
    /// Index (into the original utterance's token vector) of the last
    /// token this span was built from, inclusive.
    pub end_index: usize,
    /// Minimum token confidence across the span — mirrors
    /// `TriggerEvent::confidence` (architecture §3.5), which is defined the
    /// same way for exactly the same reason: one weak token should not let
    /// a span look more trustworthy than its weakest part.
    pub confidence: f32,
}

/// Turns one language's token set into lexicon-matchable spans.
///
/// Implementations are per-language by construction — the same interface
/// covers both "each ASR token is already a span" (space-delimited
/// languages) and "each token must be split further" (languages without
/// orthographic word boundaries).
pub trait Segmenter {
    fn segment(&self, group: &LanguageGroup) -> Vec<Span>;
}

/// Segmenter for space-delimited languages (e.g. English). The ASR already
/// tokenises on word boundaries, so each token is its own span verbatim —
/// this is the "en tokeniser" box in the architecture §3.5 diagram.
pub struct WhitespaceSegmenter;

impl Segmenter for WhitespaceSegmenter {
    fn segment(&self, group: &LanguageGroup) -> Vec<Span> {
        group
            .tokens
            .iter()
            .map(|positioned| Span {
                text: positioned.token.text.clone(),
                start_index: positioned.index,
                end_index: positioned.index,
                confidence: positioned.token.confidence,
            })
            .collect()
    }
}

/// Baseline segmenter for languages without orthographic word boundaries
/// (e.g. Chinese): splits each token's text into one span per character.
///
/// This is a deliberate simplification, documented rather than hidden: a
/// real per-language word segmenter (dictionary- or model-based) will
/// produce better lexicon-matchable spans than single characters, and
/// should replace this via [`SegmenterRouter::register`] without any
/// caller-visible change. Character spans are still correct input to
/// lexicon matching — just coarser than a dictionary segmenter's output —
/// so this is a working default rather than a stub that blocks the
/// pipeline until a full segmenter lands (the same trade the `numerals`
/// module documents for whole-text Chinese scanning).
pub struct CharSegmenter;

impl Segmenter for CharSegmenter {
    fn segment(&self, group: &LanguageGroup) -> Vec<Span> {
        group
            .tokens
            .iter()
            .flat_map(|positioned| {
                positioned.token.text.chars().map(move |ch| Span {
                    text: ch.to_string(),
                    start_index: positioned.index,
                    end_index: positioned.index,
                    confidence: positioned.token.confidence,
                })
            })
            .collect()
    }
}

/// Routes each [`LanguageGroup`] produced by [`super::group_by_language`] to
/// its own registered [`Segmenter`], falling back to a default for any
/// language that has none registered yet. This is the routing arrows in the
/// architecture §3.5 diagram: `group by language tag` on one side, a
/// per-language segmenter on the other.
pub struct SegmenterRouter {
    segmenters: std::collections::HashMap<String, Box<dyn Segmenter>>,
    default: Box<dyn Segmenter>,
}

impl SegmenterRouter {
    /// `default` is used for any language with no segmenter registered —
    /// e.g. a newly supported language that has not yet earned a dedicated
    /// implementation. Callers should generally pass [`WhitespaceSegmenter`]
    /// here, since most ASR-supported languages are space-delimited.
    pub fn new(default: Box<dyn Segmenter>) -> Self {
        SegmenterRouter {
            segmenters: std::collections::HashMap::new(),
            default,
        }
    }

    /// Registers `segmenter` for `language`'s BCP-47 primary subtag,
    /// replacing any previously registered segmenter for it.
    pub fn register(&mut self, language: &str, segmenter: Box<dyn Segmenter>) {
        self.segmenters.insert(primary_subtag(language), segmenter);
    }

    /// Groups `tokens` by language tag (dropping spans below
    /// `min_tag_confidence`, per FR-2.22) and segments each resulting group
    /// with its registered segmenter. Returns one `(language, spans)` pair
    /// per detected language, in the same order [`super::group_by_language`]
    /// produced its groups.
    pub fn route(
        &self,
        tokens: &[super::TaggedToken],
        min_tag_confidence: f32,
    ) -> Vec<(String, Vec<Span>)> {
        super::group_by_language(tokens, min_tag_confidence)
            .into_iter()
            .map(|group| {
                let segmenter = self
                    .segmenters
                    .get(&group.language)
                    .unwrap_or(&self.default);
                let spans = segmenter.segment(&group);
                (group.language, spans)
            })
            .collect()
    }

    /// [`Self::route`] followed by [`super::merge::merge_spans`]: groups,
    /// segments per language, then merges back into the single ordered span
    /// list per utterance the architecture §3.5 pipeline's "merge spans" box
    /// calls for — so callers that don't need the intermediate per-language
    /// breakdown don't have to chain both steps themselves.
    pub fn route_merged(
        &self,
        tokens: &[super::TaggedToken],
        min_tag_confidence: f32,
    ) -> Vec<Span> {
        super::merge::merge_spans(self.route(tokens, min_tag_confidence))
    }
}

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
    use crate::segment::TaggedToken;

    fn token(text: &str, lang: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    fn group(language: &str, tokens: Vec<TaggedToken>) -> LanguageGroup {
        LanguageGroup {
            language: language.to_string(),
            tokens: tokens
                .into_iter()
                .enumerate()
                .map(|(index, token)| super::super::PositionedToken { index, token })
                .collect(),
        }
    }

    #[test]
    fn whitespace_segmenter_yields_one_span_per_token() {
        let g = group("en", vec![token("hello", "en"), token("world", "en")]);
        let spans = WhitespaceSegmenter.segment(&g);
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0].text, "hello");
        assert_eq!(spans[1].text, "world");
    }

    #[test]
    fn char_segmenter_splits_a_token_into_one_span_per_character() {
        let g = group("zh", vec![token("你好", "zh")]);
        let spans = CharSegmenter.segment(&g);
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0].text, "你");
        assert_eq!(spans[1].text, "好");
        // both spans trace back to the one token they were split from
        assert_eq!(spans[0].start_index, 0);
        assert_eq!(spans[1].start_index, 0);
    }

    #[test]
    fn router_dispatches_each_group_to_its_registered_segmenter() {
        let mut router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        router.register("zh", Box::new(CharSegmenter));

        let tokens = vec![token("你好", "zh"), token("world", "en")];
        let routed = router.route(&tokens, 0.6);

        let zh = routed.iter().find(|(lang, _)| lang == "zh").unwrap();
        let en = routed.iter().find(|(lang, _)| lang == "en").unwrap();
        assert_eq!(zh.1.len(), 2); // char-segmented
        assert_eq!(en.1.len(), 1); // whitespace-segmented, ASR token verbatim
    }

    #[test]
    fn unregistered_language_falls_back_to_the_default_segmenter() {
        let router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        let tokens = vec![token("bonjour", "fr")];
        let routed = router.route(&tokens, 0.6);
        assert_eq!(routed[0].0, "fr");
        assert_eq!(routed[0].1.len(), 1);
        assert_eq!(routed[0].1[0].text, "bonjour");
    }

    #[test]
    fn registering_a_language_replaces_its_previous_segmenter() {
        let mut router = SegmenterRouter::new(Box::new(WhitespaceSegmenter));
        router.register("zh", Box::new(WhitespaceSegmenter));
        router.register("zh", Box::new(CharSegmenter));

        let tokens = vec![token("你好", "zh")];
        let routed = router.route(&tokens, 0.6);
        assert_eq!(routed[0].1.len(), 2); // CharSegmenter won, not the first registration
    }
}
