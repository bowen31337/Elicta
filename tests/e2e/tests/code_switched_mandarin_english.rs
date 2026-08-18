//! End-to-end: a code-switched Mandarin-English utterance is segmented,
//! per-token language tags route each token to its own language's lexicon,
//! and a token whose language tag was emitted at low confidence never
//! reaches a lexicon at all (PRD FR-2.13, FR-2.22, NFR-5.3, architecture
//! §3.5).
//!
//! `language::segment` and `trigger_gate::lexicon` are deliberately not
//! linked to each other in production yet (see `trigger_gate::lexicon`'s
//! module doc) — each re-derives its own field-identical `TaggedToken`.
//! This test is where both run together: the real Mandarin segmenter
//! produces the utterance's tokens, and the real lexicon router decides
//! which of them become nudge candidates.

use language::segment::{segment_utterance, DictionarySegmenter};
use trigger_gate::lexicon::{Lexicon, LexiconRouter, TaggedToken};

const MIN_TAG_CONFIDENCE: f32 = 0.6;

/// Stands in for what an ASR vendor emits alongside each token's text: a
/// per-token BCP-47 language tag. Chosen by script here because this test's
/// utterance mixes only Han and Latin script, the same simplification the
/// architecture doc's own worked examples use.
fn language_tag_for(text: &str) -> &'static str {
    let is_han = text.chars().next().map(|c| matches!(c as u32, 0x4E00..=0x9FFF)).unwrap_or(false);
    if is_han {
        "zh"
    } else {
        "en"
    }
}

/// Stands in for the ASR vendor's per-token language-tag confidence. Every
/// token is confidently tagged except "也许" ("maybe"), which arrives with a
/// deliberately low tag confidence — the low-confidence span this test
/// proves produces no nudge.
fn lang_confidence_for(text: &str) -> f32 {
    match text {
        "也许" => 0.2,
        _ => 0.92,
    }
}

fn index_of(tokens: &[TaggedToken], text: &str) -> usize {
    tokens.iter().position(|t| t.text == text).unwrap_or_else(|| panic!("token {text:?} present"))
}

#[test]
fn code_switched_utterance_routes_tokens_and_gates_the_low_confidence_span() {
    // PRD FR-2.13's own style of example, extended with one ambiguity term
    // per language plus a deliberately low-confidence Chinese span.
    let text = "这个 API 大概 needs several fixes 也许 明天 的 会议";

    let segmenter = DictionarySegmenter::with_builtin_zh();
    let segments = segment_utterance(text, &segmenter);
    assert!(
        segments.iter().any(|s| s.text == "也许"),
        "the low-confidence span must actually be present in the transcript, not merely absent"
    );

    let tokens: Vec<TaggedToken> = segments
        .iter()
        .map(|segment| TaggedToken {
            text: segment.text.clone(),
            confidence: 0.95,
            lang: language_tag_for(&segment.text).to_string(),
            lang_confidence: lang_confidence_for(&segment.text),
        })
        .collect();

    let mut router = LexiconRouter::new();
    router.register(Lexicon::new("en", ["several"]));
    router.register(Lexicon::new("zh", ["大概", "也许"]));

    let matches = router.run(&tokens, MIN_TAG_CONFIDENCE);

    // Token-level tags route correctly: each language produced a match from
    // its own lexicon only, and neither half of the code-switched utterance
    // was discarded in favour of the other.
    let en_matches: Vec<_> = matches.iter().filter(|m| m.language == "en").collect();
    let zh_matches: Vec<_> = matches.iter().filter(|m| m.language == "zh").collect();
    assert_eq!(en_matches.len(), 1, "the English half must not be discarded");
    assert_eq!(zh_matches.len(), 1, "the Chinese half must not be discarded");
    assert_eq!(en_matches[0].term, "several");
    assert_eq!(en_matches[0].token_index, index_of(&tokens, "several"));
    assert_eq!(zh_matches[0].term, "大概");
    assert_eq!(zh_matches[0].token_index, index_of(&tokens, "大概"));

    // Low-confidence span produces no nudge: "也许" carries a curated zh
    // ambiguity term but was tagged below the confidence gate, so it must
    // never surface as a lexicon match / nudge candidate at all.
    assert!(
        !matches.iter().any(|m| m.term == "也许"),
        "a low-confidence span must not produce a nudge"
    );

    // Control: prove the suppression above is specifically the confidence
    // gate, not a missing term — remove the gate and the same token matches.
    let ungated_matches = router.run(&tokens, 0.0);
    assert!(
        ungated_matches.iter().any(|m| m.term == "也许"),
        "control: the term is present and matches once the confidence gate is removed"
    );

    // Matches restore original utterance order across the language switch.
    let indices: Vec<usize> = matches.iter().map(|m| m.token_index).collect();
    let mut sorted = indices.clone();
    sorted.sort_unstable();
    assert_eq!(indices, sorted, "matches must be ordered by original token index");
}
