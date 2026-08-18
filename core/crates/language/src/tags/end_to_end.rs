use std::collections::HashMap;

/// A single already-transcribed token: text the ASR model produced, plus the
/// per-token language tag it emitted as a by-product of producing that text
/// (PRD FR-2.12, FR-2.13; architecture §3.2's `Token`). Mirrors
/// `segment::TaggedToken`'s field set; duplicated locally rather than
/// imported because `tags` and `segment` are deliberately independent
/// modules of this crate (see this directory's `HANDOFF.md`), each wired
/// into `lib.rs` and consumed on its own — neither reaches across into the
/// other's types, same reason every sibling file here re-derives
/// `primary_subtag` instead of sharing one copy.
#[derive(Debug, Clone, PartialEq)]
pub struct EndToEndToken {
    pub text: String,
    /// BCP-47 tag for this token specifically, not the utterance.
    pub language: String,
    /// Confidence in `language`, not in `text`. Gates aggregation in
    /// [`DominantLanguageResolver::resolve`] the same way it gates every
    /// other tag-confidence check in this directory (FR-2.22).
    pub lang_confidence: f32,
}

/// Reconstructs an utterance's transcribed text from `tokens`, in their
/// original order.
///
/// This is FR-2.12's structural proof for this directory: it is the only
/// function here that produces transcript text, and its signature makes it
/// impossible to gate that production on a language decision — it never
/// reads `language` or `lang_confidence` at all, so a token with an unknown,
/// low-confidence, or entirely absent language tag contributes its text
/// exactly as readily as a confidently-tagged one. Per-token tags are
/// consumed separately, downstream, by [`DominantLanguageResolver`] and by
/// every other tracker in this directory — never as a precondition for
/// text to exist in the first place.
pub fn transcript_text(tokens: &[EndToEndToken]) -> String {
    tokens.iter().map(|token| token.text.as_str()).collect::<Vec<_>>().join(" ")
}

/// The single `(language, confidence)` observation aggregated from an
/// utterance's per-token tags, shaped to feed directly into
/// [`super::participant::ParticipantLanguageTags::observe`],
/// [`super::detected_languages::DetectedLanguagePanel::observe`], or
/// [`super::tier_drift::TierDriftMonitor::observe`].
#[derive(Debug, Clone, PartialEq)]
pub struct DominantLanguage {
    pub language: String,
    pub confidence: f32,
}

/// Derives the dominant-language observation for a code-switched utterance
/// from its already-transcribed tokens (PRD FR-2.12).
///
/// Every tracker in this directory takes a `language: &str, confidence: f32`
/// observation as an opaque input; nothing else here shows where that value
/// comes from. This is that derivation, and its input type is the proof: an
/// [`EndToEndToken`] only exists once the ASR model has already produced its
/// `text`, so there is no path through this crate that decides a language
/// before transcription — routing and aggregation both happen strictly
/// after, over tags the model emitted as a by-product, matching the
/// `segment::group_by_language` convention this mirrors at the tags layer
/// (architecture §3.5).
#[derive(Debug, Clone, Copy)]
pub struct DominantLanguageResolver {
    /// Mirrors the tag-confidence gate already applied to every other
    /// tracker in this directory (FR-2.22): a token below this confidence
    /// contributes neither to a language's aggregate weight nor its
    /// reported confidence.
    min_confidence: f32,
}

impl Default for DominantLanguageResolver {
    fn default() -> Self {
        DominantLanguageResolver { min_confidence: 0.6 }
    }
}

impl DominantLanguageResolver {
    pub fn new() -> Self {
        DominantLanguageResolver::default()
    }

    /// Overrides the default minimum tag confidence.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// Aggregates `tokens` (BCP-47 primary subtag) into the language with
    /// the highest total confidence, reporting that language's mean
    /// confidence across the tokens that counted toward it. Tokens below
    /// `min_confidence` are dropped before aggregation, same as every other
    /// confidence gate in this directory — a single noisy tag must never
    /// tip which language an utterance is attributed to. A tie in total
    /// confidence keeps whichever language was seen first in `tokens`,
    /// matching `AttendeeLanguagePreferences`' tie-breaking convention.
    /// Returns `None` when no token clears the bar.
    pub fn resolve(&self, tokens: &[EndToEndToken]) -> Option<DominantLanguage> {
        let mut order: Vec<String> = Vec::new();
        let mut totals: HashMap<String, f32> = HashMap::new();
        let mut counts: HashMap<String, usize> = HashMap::new();

        for token in tokens {
            if token.lang_confidence < self.min_confidence {
                continue;
            }

            let language = primary_subtag(&token.language);
            if !totals.contains_key(&language) {
                order.push(language.clone());
            }
            *totals.entry(language.clone()).or_insert(0.0) += token.lang_confidence;
            *counts.entry(language).or_insert(0) += 1;
        }

        let mut best: Option<(String, f32)> = None;
        for language in order {
            let total = totals[&language];
            let is_better = match &best {
                Some((_, best_total)) => total > *best_total,
                None => true,
            };
            if is_better {
                best = Some((language, total));
            }
        }

        best.map(|(language, total)| {
            let count = counts[&language] as f32;
            DominantLanguage { language: language.clone(), confidence: total / count }
        })
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" tag a
/// token the same way. Matches the convention already used by every sibling
/// in this directory; duplicated locally since none of them expose it.
fn primary_subtag(language: &str) -> String {
    language.split(['-', '_']).next().unwrap_or(language).to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn token(text: &str, language: &str, lang_confidence: f32) -> EndToEndToken {
        EndToEndToken { text: text.to_string(), language: language.to_string(), lang_confidence }
    }

    #[test]
    fn transcript_text_joins_tokens_in_order() {
        let tokens = vec![token("这个", "zh", 0.9), token("API", "en", 0.9), token("的", "zh", 0.9)];
        assert_eq!(transcript_text(&tokens), "这个 API 的");
    }

    #[test]
    fn transcript_text_ignores_language_and_confidence_entirely() {
        let tokens = vec![
            token("hello", "", 0.0),
            token("world", "xx-not-a-real-tag", -1.0),
        ];
        assert_eq!(transcript_text(&tokens), "hello world");
    }

    #[test]
    fn transcript_text_of_no_tokens_is_empty() {
        assert_eq!(transcript_text(&[]), "");
    }

    #[test]
    fn transcript_text_never_reorders_a_code_switched_utterance() {
        let tokens = vec![
            token("这个", "zh", 0.9),
            token("API", "en", 0.9),
            token("的", "zh", 0.9),
            token("latency", "en", 0.9),
            token("要求是什么", "zh", 0.9),
        ];
        assert_eq!(transcript_text(&tokens), "这个 API 的 latency 要求是什么");
    }

    #[test]
    fn resolve_on_no_tokens_returns_none() {
        let resolver = DominantLanguageResolver::new();
        assert_eq!(resolver.resolve(&[]), None);
    }

    #[test]
    fn resolve_with_all_tokens_below_threshold_returns_none() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![token("hi", "en", 0.2), token("lo", "en", 0.3)];
        assert_eq!(resolver.resolve(&tokens), None);
    }

    #[test]
    fn resolve_single_language_reports_mean_confidence() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![token("hello", "en", 0.8), token("there", "en", 0.6)];

        let dominant = resolver.resolve(&tokens).expect("confident tokens");
        assert_eq!(dominant.language, "en");
        assert!((dominant.confidence - 0.7).abs() < 1e-6);
    }

    #[test]
    fn resolve_code_switched_utterance_picks_the_stronger_language() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![
            token("这个", "zh", 0.9),
            token("的", "zh", 0.9),
            token("要求是什么", "zh", 0.9),
            token("API", "en", 0.9),
        ];

        let dominant = resolver.resolve(&tokens).expect("confident tokens");
        assert_eq!(dominant.language, "zh");
    }

    #[test]
    fn resolve_drops_low_confidence_tokens_before_aggregating() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![
            token("API", "en", 0.9),
            token("noise", "zh", 0.99),
            token("noise", "zh", 0.1),
        ];

        // Without the drop, zh's raw total (1.09) would beat en's (0.9); the
        // low-confidence zh token must not count toward either its total or
        // its mean.
        let dominant = resolver.resolve(&tokens).expect("confident tokens");
        assert_eq!(dominant.language, "zh");
        assert_eq!(dominant.confidence, 0.99);
    }

    #[test]
    fn resolve_tie_keeps_the_first_seen_language() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![token("hello", "en", 0.9), token("你好", "zh", 0.9)];

        let dominant = resolver.resolve(&tokens).expect("confident tokens");
        assert_eq!(dominant.language, "en");
    }

    #[test]
    fn resolve_collapses_bcp47_region_and_script_subtags() {
        let resolver = DominantLanguageResolver::new();
        let tokens = vec![token("hello", "en-US", 0.9), token("hi", "EN", 0.9)];

        let dominant = resolver.resolve(&tokens).expect("confident tokens");
        assert_eq!(dominant.language, "en");
        assert_eq!(dominant.confidence, 0.9);
    }

    #[test]
    fn custom_confidence_threshold_gates_resolution() {
        let resolver = DominantLanguageResolver::new().with_min_confidence(0.95);
        let tokens = vec![token("hello", "en", 0.9)];

        assert_eq!(resolver.resolve(&tokens), None);

        let tokens = vec![token("hello", "en", 0.96)];
        assert!(resolver.resolve(&tokens).is_some());
    }
}
