//! The FR-5.1 gate-evaluation loop: "System evaluates every finalised
//! utterance whose speaker tag is not operator against the trigger gate."
//! Architecture §3.5 states this as FR-5.1 refined — "requires every
//! finalised utterance to be evaluated; the gate refines this by evaluating
//! only utterances whose `speaker` is not `Operator`, since a nudge
//! prompting the operator to interrogate their own sentence is never
//! useful."
//!
//! Every other module in this crate proves one link of the chain in
//! isolation: [`super::router::LexiconRouter`] proves per-language routing,
//! [`crate::parse::gate_span_confidence`] proves span-confidence gating. Both
//! HANDOFFs left "the overall gate evaluation loop that decides which
//! utterances reach this module at all" (feature 141) explicitly out of
//! scope. [`evaluate_utterance`] is that loop: it is the first place a
//! `speaker` tag and a lexicon match ever meet.
//!
//! ```text
//! FinalisedUtterance ──▶ speaker == Operator? ──yes──▶ not evaluated (None)
//!                              │no
//!                              ▼
//!                     LexiconRouter::run (per-language isolation)
//!                              │
//!                              ▼
//!                   gate_span_confidence (per match)
//!                              │
//!                              ▼
//!         GateDecision { utterance_id, events, latency }
//! ```
//!
//! Feature 143 ("System completes the deterministic lexicon scan in under 20
//! milliseconds with no model call on the path") is proved by this module in
//! two parts: "no model call on the path" holds structurally, not by
//! convention — `evaluate_utterance`'s only dependencies are
//! [`LexiconRouter::run`] (Aho-Corasick over a curated in-memory term list)
//! and [`gate_span_confidence`] (a float comparison); neither this crate nor
//! its `Cargo.toml` has any model/inference dependency to call in the first
//! place. "Done when each utterance emits a gate latency measurement" is
//! `GateDecision::latency`: every evaluated utterance's routing-and-gating
//! work is timed with [`Instant`], and the elapsed [`Duration`] rides on the
//! same `GateDecision` the caller already receives — a measurement, not a
//! side channel a caller has to opt into.

use std::ops::Range;
use std::time::{Duration, Instant};

use crate::parse::{gate_span_confidence, TriggerEvent, UtteranceId};

use super::grouping::TaggedToken;
use super::router::LexiconRouter;

/// Who a [`FinalisedUtterance`] is attributed to (architecture §3.3, §3.5,
/// PRD FR-2.3). Mirrors `asr-live::backend::event::SpeakerTag` field-for-
/// field, duplicated locally rather than imported for the same reason
/// [`super::grouping::TaggedToken`] duplicates `language::segment`'s type of
/// the same name (see this directory's `mod.rs`): `trigger-gate` has no
/// `Cargo.toml` dependency on `asr-live` in this worktree, so there is no
/// way to depend on its type today. Re-point at the shared type once crate
/// wiring links the two.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpeakerTag {
    Operator,
    Participant(String),
    Unknown,
}

/// A finalised utterance (PRD FR-2.3) as the trigger gate needs it: enough
/// to decide whether FR-5.1 requires evaluating it at all (`speaker`), and
/// what to scan if so (`tokens`). Deliberately narrower than
/// `asr-live::backend::event::FinalUtterance` — `text`, `stream_id`,
/// `start`/`end`, and `audio_ref` are that crate's own bookkeeping, not
/// anything this evaluation needs.
#[derive(Debug, Clone, PartialEq)]
pub struct FinalisedUtterance {
    pub id: UtteranceId,
    pub speaker: SpeakerTag,
    pub tokens: Vec<TaggedToken>,
}

/// The trigger gate's uniform per-utterance output for FR-5.1: every
/// utterance [`evaluate_utterance`] actually evaluates gets exactly one of
/// these back, carrying one [`TriggerEvent`] per candidate span the lexicon
/// matched (possibly zero — "nothing matched" is itself a decision, not the
/// absence of one).
#[derive(Debug, Clone, PartialEq)]
pub struct GateDecision {
    pub utterance_id: UtteranceId,
    pub events: Vec<TriggerEvent>,
    /// Wall-clock time [`evaluate_utterance`] spent routing `utterance`
    /// through its per-language lexicons and gating every resulting match's
    /// span confidence (feature 143) — the deterministic lexicon scan this
    /// `GateDecision` is the result of, with no model call anywhere on that
    /// path. Populated on every `GateDecision` this function returns, never
    /// left at a placeholder zero: "each utterance emits a gate latency
    /// measurement" means a real measurement rides on every decision, not
    /// just the ones a caller happens to check.
    pub latency: Duration,
}

/// Evaluates `utterance` against the trigger gate (PRD FR-5.1): routes its
/// tokens through `router`'s per-language lexicons (dropping any tagged
/// below `min_tag_confidence`, per FR-2.22), then gates every resulting
/// match's span confidence against `min_span_confidence` (NFR-5.6).
///
/// Returns `None` for an `Operator`-tagged utterance without running any of
/// the above — architecture §3.5's refinement of FR-5.1, "evaluating only
/// utterances whose `speaker` is not `Operator`". Every other speaker tag,
/// including `Unknown` (the capture path could not attribute the utterance
/// at all), is evaluated: FR-5.1 excludes exactly one tag, not "anything
/// less than certain".
///
/// Every evaluated utterance gets back `Some(GateDecision)`, never `None` —
/// this is the "every non-operator utterance emits a gate decision"
/// contract: an utterance with zero lexicon matches still produces a
/// `GateDecision` with an empty `events` vector, rather than nothing at all.
///
/// `GateDecision::latency` (feature 143) is timed around exactly the
/// deterministic work this function does to produce `events` — the
/// per-language lexicon scan (`router.run`) and the span-confidence gate over
/// every resulting match — so it measures the real cost of this utterance's
/// gate evaluation, not a fixed or estimated figure.
pub fn evaluate_utterance(
    utterance: &FinalisedUtterance,
    router: &LexiconRouter,
    min_tag_confidence: f32,
    min_span_confidence: f32,
) -> Option<GateDecision> {
    if utterance.speaker == SpeakerTag::Operator {
        return None;
    }

    let started = Instant::now();

    let events = router
        .run(&utterance.tokens, min_tag_confidence)
        .into_iter()
        .map(|matched| {
            let span = token_span(&utterance.tokens, matched.token_index, &matched.span);
            let confidence = utterance.tokens[matched.token_index].confidence;
            gate_span_confidence(
                utterance.id.clone(),
                span,
                &[confidence],
                min_span_confidence,
            )
        })
        .collect();

    let latency = started.elapsed();

    Some(GateDecision {
        utterance_id: utterance.id.clone(),
        events,
        latency,
    })
}

/// The byte range `match_span` (a [`super::terms::LexiconMatch::span`],
/// already scoped to `tokens[token_index]`'s own text) would occupy within
/// `tokens` reconstructed as one string, joined by a single ASCII space —
/// i.e. the offending phrase's own position, not the whole token's (FR-5.2:
/// "returning the matched span").
///
/// Neither `TaggedToken` nor `asr-live`'s own `Token` carry a byte offset
/// into the source utterance text — `parse::HANDOFF.md` flags turning a
/// `LexiconMatch` into `gate_span_confidence`'s `(span, word_confidences)`
/// as unresolved for exactly this reason. Reconstructing via space-joining
/// is a simplifying assumption, not a guarantee that it matches the
/// vendor's own original spacing/punctuation byte-for-byte; nothing
/// downstream of `TriggerEvent.span` in this crate interprets it against
/// the literal utterance text today, only against this crate's own
/// reconstruction.
fn token_span(
    tokens: &[TaggedToken],
    token_index: usize,
    match_span: &Range<usize>,
) -> Range<usize> {
    let token_start: usize = tokens[..token_index]
        .iter()
        .map(|token| token.text.len() + 1)
        .sum();
    (token_start + match_span.start)..(token_start + match_span.end)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexicon::terms::Lexicon;
    use crate::parse::{SuppressionReason, TriggerKind};

    fn token(text: &str, lang: &str, confidence: f32) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    fn router_with_en_and_zh_lexicons() -> LexiconRouter {
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en-test-v1", "en", ["several", "a lot"]));
        router.register(Lexicon::new("zh-test-v1", "zh", ["一些"]));
        router
    }

    #[test]
    fn an_operator_utterance_is_never_evaluated() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-1".to_string(),
            speaker: SpeakerTag::Operator,
            tokens: vec![
                token("we", "en", 0.9),
                token("need", "en", 0.9),
                token("several", "en", 0.9),
            ],
        };

        assert_eq!(evaluate_utterance(&utterance, &router, 0.6, 0.6), None);
    }

    #[test]
    fn a_participant_utterance_with_a_match_fires() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-2".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![
                token("we", "en", 0.9),
                token("need", "en", 0.9),
                token("several", "en", 0.95),
            ],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6)
            .expect("participant utterance is evaluated");

        assert_eq!(decision.utterance_id, "utt-2");
        assert_eq!(decision.events.len(), 1);
        assert_eq!(decision.events[0].kind, TriggerKind::Fired);
    }

    #[test]
    fn an_unknown_speaker_utterance_is_also_evaluated() {
        // FR-5.1 excludes exactly the `Operator` tag, not "anything short of
        // a confirmed participant".
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-3".to_string(),
            speaker: SpeakerTag::Unknown,
            tokens: vec![token("several", "en", 0.95)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6)
            .expect("Unknown speaker is still evaluated");

        assert_eq!(decision.events.len(), 1);
    }

    #[test]
    fn a_participant_utterance_with_no_lexicon_match_still_emits_a_decision() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-4".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![token("precisely", "en", 0.95)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6)
            .expect("evaluated utterances always emit a decision");

        assert!(decision.events.is_empty());
    }

    #[test]
    fn a_match_below_span_confidence_is_suppressed_not_dropped() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-5".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![token("several", "en", 0.2)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        assert_eq!(decision.events.len(), 1);
        assert!(matches!(
            &decision.events[0].kind,
            TriggerKind::Suppressed(SuppressionReason::SpanConfidenceBelowThreshold { confidence, .. })
                if *confidence == 0.2
        ));
    }

    #[test]
    fn a_code_switched_utterance_emits_one_event_per_language_match() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-6".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![token("several", "en", 0.9), token("一些", "zh", 0.9)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        assert_eq!(decision.events.len(), 2);
        assert!(decision.events.iter().all(|e| e.kind == TriggerKind::Fired));
    }

    #[test]
    fn a_tokens_below_tag_confidence_never_produces_an_event_for_it() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-7".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![TaggedToken {
                text: "several".to_string(),
                confidence: 0.9,
                lang: "en".to_string(),
                lang_confidence: 0.2, // below min_tag_confidence
            }],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        assert!(decision.events.is_empty());
    }

    #[test]
    fn event_span_reflects_the_matched_tokens_own_position() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-8".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![
                token("we", "en", 0.9),
                token("need", "en", 0.9),
                token("several", "en", 0.9),
            ],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        // "we need several" joined by single spaces: "we"(0..2) " "(2)
        // "need"(3..7) " "(7) "several"(8..15).
        assert_eq!(decision.events[0].span, Some(8..15));
    }

    #[test]
    fn event_span_narrows_to_the_matched_phrase_not_the_whole_token() {
        // A single ASR token can carry more than one word (e.g. "we need
        // several" as one hypothesis, as `hold.rs`'s own tests construct).
        // The offending span (FR-5.2) must cover only "several", not the
        // token's full text.
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-10".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![
                token("preface", "en", 0.9),
                token("we need several", "en", 0.9),
            ],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        // "preface"(0..7) " "(7) "we need several"(8..23), and "several"
        // itself sits at 8+8..8+15 = 16..23 within the joined string.
        assert_eq!(decision.events.len(), 1);
        assert_eq!(decision.events[0].span, Some(16..23));
    }

    #[test]
    fn an_operator_utterance_is_never_evaluated_even_with_a_matching_term() {
        // Guards against a future change accidentally routing an Operator
        // utterance through the lexicon before checking speaker.
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-9".to_string(),
            speaker: SpeakerTag::Operator,
            tokens: vec![token("several", "en", 0.95)],
        };

        assert!(evaluate_utterance(&utterance, &router, 0.6, 0.6).is_none());
    }

    #[test]
    fn a_participant_utterance_with_a_match_carries_a_gate_latency_measurement() {
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-11".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![token("several", "en", 0.95)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        // Feature 143: "completes the deterministic lexicon scan in under 20
        // milliseconds" — a real elapsed measurement, not a stand-in zero
        // value, and comfortably inside the budget for a single-token scan
        // over a two-language, hand-built test lexicon.
        assert!(decision.latency < Duration::from_millis(20));
    }

    #[test]
    fn an_utterance_with_no_match_still_carries_a_latency_measurement() {
        // "each utterance emits a gate latency measurement" is not
        // conditional on the scan finding anything — a decision with zero
        // events still did the deterministic work of scanning for one.
        let router = router_with_en_and_zh_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-12".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![token("precisely", "en", 0.95)],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        assert!(decision.events.is_empty());
        assert!(decision.latency < Duration::from_millis(20));
    }

    #[test]
    fn a_realistic_code_switched_utterance_against_the_full_curated_lexicons_clears_the_20ms_budget(
    ) {
        // The budget feature 143 actually names: every curated lexicon this
        // build ships (not a handful of hand-picked test terms), scanned
        // over a longer, mixed-language utterance closer to real ASR output
        // than this file's other single- or few-token fixtures.
        let router = LexiconRouter::with_curated_lexicons();
        let utterance = FinalisedUtterance {
            id: "utt-13".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            tokens: vec![
                token("we", "en", 0.9),
                token("need", "en", 0.9),
                token("several", "en", 0.9),
                token("robust", "en", 0.9),
                token("and", "en", 0.9),
                token("scalable", "en", 0.9),
                token("这个", "zh", 0.9),
                token("API", "en", 0.9),
                token("的", "zh", 0.9),
                token("差不多", "zh", 0.9),
                token("可以", "zh", 0.9),
                token("尽快", "zh", 0.9),
                token("上线", "zh", 0.9),
            ],
        };

        let decision = evaluate_utterance(&utterance, &router, 0.6, 0.6).unwrap();

        assert!(!decision.events.is_empty());
        assert!(decision.latency < Duration::from_millis(20));
    }
}
