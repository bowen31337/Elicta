//! End-to-end: with the inference endpoint unreachable, `trigger-gate`'s
//! real deterministic (lexicon) path keeps firing exactly the nudges it
//! would with a healthy endpoint, and the panel's badge reflects the
//! endpoint outage rather than silently degrading (PRD NFR-4.1).
//!
//! `trigger-gate` has no dependency on any inference client today — its
//! lexicon path is pure text matching (see `lexicon/terms.rs`'s doc: "a
//! plain case-insensitive substring scan"), and no production crate for the
//! model-trigger's inference client or the panel's badge chrome exists yet
//! in this workspace. This test supplies both as local stand-ins — an
//! `InferenceEndpoint` seam an unreachable-endpoint double can fail, and a
//! `PanelBadge` derived from that outcome — so the one real guarantee PRD
//! NFR-4.1 depends on can be exercised now: the deterministic path must
//! never even glance at whether the inference endpoint answered.

use trigger_gate::lexicon::{Lexicon, LexiconMatch, LexiconRouter, TaggedToken};

/// Stands in for the not-yet-built client that reaches the model-trigger's
/// inference endpoint. `trigger-gate`'s deterministic lexicon path never
/// implements or calls this — that separation is exactly what this test
/// proves holds under failure.
trait InferenceEndpoint {
    fn suggest(&self, transcript_window: &str) -> Result<ModelSuggestion, InferenceError>;
}

#[derive(Debug, Clone, PartialEq)]
struct ModelSuggestion {
    text: String,
}

#[derive(Debug, Clone, PartialEq)]
struct InferenceError(String);

/// A healthy endpoint, used as this test's control case.
struct RespondingEndpoint;

impl InferenceEndpoint for RespondingEndpoint {
    fn suggest(&self, transcript_window: &str) -> Result<ModelSuggestion, InferenceError> {
        Ok(ModelSuggestion { text: format!("model nudge for: {transcript_window}") })
    }
}

/// The failure mode PRD NFR-4.1 names explicitly: the inference endpoint
/// times out rather than refusing outright.
struct UnreachableEndpoint;

impl InferenceEndpoint for UnreachableEndpoint {
    fn suggest(&self, _transcript_window: &str) -> Result<ModelSuggestion, InferenceError> {
        Err(InferenceError("inference endpoint timed out".to_string()))
    }
}

/// Operator-facing panel badge (PRD NFR-4.1). No production chrome for this
/// exists yet — `apps/desktop`'s panel only has a language-tier badge today
/// (see `apps/desktop/src/features/panel/language/tierCapability.ts`) — so
/// this is the minimal shape the real badge will need: distinguishing a
/// healthy endpoint from a degraded one, with the reason preserved for the
/// operator-facing message.
#[derive(Debug, Clone, PartialEq)]
enum PanelBadge {
    Normal,
    Degraded { reason: String },
}

fn panel_badge_for(inference_result: &Result<ModelSuggestion, InferenceError>) -> PanelBadge {
    match inference_result {
        Ok(_) => PanelBadge::Normal,
        Err(InferenceError(reason)) => PanelBadge::Degraded { reason: reason.clone() },
    }
}

/// What the panel actually renders this tick: the badge, whatever the
/// deterministic gate produced, and whatever the model path produced (if
/// anything). Built from both feeds independently — the deterministic feed
/// never consults the inference result, and the badge never consults the
/// deterministic feed — so a defect that accidentally coupled the two would
/// show up here, not be hidden by this struct's own construction.
struct PanelState {
    badge: PanelBadge,
    deterministic_nudges: Vec<LexiconMatch>,
    model_nudge: Option<ModelSuggestion>,
}

fn build_panel_state(
    deterministic_nudges: Vec<LexiconMatch>,
    inference_result: Result<ModelSuggestion, InferenceError>,
) -> PanelState {
    let badge = panel_badge_for(&inference_result);
    PanelState { badge, deterministic_nudges, model_nudge: inference_result.ok() }
}

fn token(text: &str, lang: &str) -> TaggedToken {
    TaggedToken { text: text.to_string(), confidence: 0.95, lang: lang.to_string(), lang_confidence: 0.92 }
}

#[test]
fn deterministic_triggers_keep_firing_and_the_panel_degrades_when_the_inference_endpoint_is_unreachable(
) {
    // The utterance carrying a curated ambiguity term, run through the real
    // `trigger-gate` lexicon path exactly as the live pipeline would.
    let tokens = vec![
        token("We", "en"),
        token("need", "en"),
        token("several", "en"),
        token("fixes", "en"),
        token("before", "en"),
        token("the", "en"),
        token("client", "en"),
        token("call", "en"),
    ];
    let mut router = LexiconRouter::new();
    router.register(Lexicon::new("en", ["several"]));
    let transcript_window = "We need several fixes before the client call";

    // Control: a healthy endpoint produces a normal badge alongside the
    // deterministic match, so the degraded case below is shown to be a
    // genuine state change, not this test's only possible outcome.
    let healthy_matches = router.run(&tokens, 0.6);
    let healthy_state =
        build_panel_state(healthy_matches, RespondingEndpoint.suggest(transcript_window));
    assert_eq!(healthy_state.badge, PanelBadge::Normal);
    assert_eq!(healthy_state.deterministic_nudges.len(), 1);
    assert_eq!(healthy_state.deterministic_nudges[0].term, "several");
    assert!(healthy_state.model_nudge.is_some());

    // The endpoint goes unreachable. The deterministic gate is re-run from
    // the same tokens and router — nothing about this call path touches the
    // inference endpoint at all.
    let degraded_matches = router.run(&tokens, 0.6);
    let inference_outcome = UnreachableEndpoint.suggest(transcript_window);
    assert!(inference_outcome.is_err(), "the endpoint must actually be unreachable in this test");

    let degraded_state = build_panel_state(degraded_matches, inference_outcome);

    // The panel displays a degraded badge naming the failure.
    match &degraded_state.badge {
        PanelBadge::Degraded { reason } => {
            assert!(reason.contains("timed out"), "badge should carry the operator-facing reason")
        }
        PanelBadge::Normal => panic!("badge must degrade when the inference endpoint is unreachable"),
    }

    // Deterministic triggers keep firing: the exact same match the healthy
    // run produced, unaffected by the endpoint's outage.
    assert_eq!(degraded_state.deterministic_nudges, healthy_state.deterministic_nudges);
    assert_eq!(degraded_state.deterministic_nudges.len(), 1);

    // No model-path nudge is fabricated in place of the failed call.
    assert!(degraded_state.model_nudge.is_none());
}
