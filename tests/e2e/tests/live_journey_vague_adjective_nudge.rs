//! End-to-end: the live journey from capture start to a single panel nudge.
//! Capture starts, the operator's counterpart speaks an utterance carrying a
//! vague adjective ("fast" — one of FR-5.2's own named examples: "fast",
//! "scalable", "user-friendly", "a lot", "soon"), and the panel displays
//! exactly one nudge carrying its trigger reason (FR-5.11) — all inside the
//! deterministic path's latency budget. Architecture §5 puts that budget in
//! concrete terms: "Detecting an unquantified adjective is a lexicon scan;
//! responding to it is a template instantiation against a pre-written
//! candidate. End to end, under 100ms" — this refines NFR-1's 300-800ms
//! model-assisted-trigger budget down to a much tighter number for exactly
//! the deterministic path this test drives.
//!
//! `capture`, `asr-live` and `trigger-gate` are three separate crates with
//! no `Cargo.toml` linking any of them to each other yet (see
//! `trigger_gate::lexicon`'s own module doc, and `asr-live/src/backend`'s
//! `HANDOFF.md` — neither depends on `capture`, and `trigger-gate` doesn't
//! depend on `asr-live`). This crate is the one place, per its own `lib.rs`
//! doc, that drives real crates together as the documented pipeline instead
//! of asserting on each in isolation. It supplies only the one seam that
//! doesn't exist in any production crate yet: the panel's rendered nudge
//! (mirroring `apps/desktop`'s `Nudge` type — `stub` plus a required
//! `triggerReason` field, per that type's own doc citing FR-5.11).
//!
//! Pipeline driven, each stage using the real crate:
//! ```text
//! capture::ring        -- normalises raw audio to 16kHz mono PCM16
//! capture::state        -- retains the segment backing the utterance (FR-1.7)
//! asr_live::backend     -- finalises the utterance into tokens (FR-2.1-2.3)
//! trigger_gate::lexicon -- scans tokens for a curated vague-adjective term
//! (local)               -- renders the one nudge the panel would display
//! ```

use std::time::{Duration, Instant};

use asr_live::backend::{ImmutablePartialFakeBackend, TranscriptionBackend, TranscriptionEvent};
use capture::ring::{AudioFormat, NormalizingPipeline, RawFrame};
use capture::state::SegmentStore;
use trigger_gate::lexicon::{Lexicon, LexiconMatch, LexiconRouter, TaggedToken};

/// FR-5.2's own named examples of unquantified adjectives and vague
/// quantifiers, curated into one lexicon exactly the way section 8.2a
/// describes — a lexicon per language, not a translation of another one.
fn vague_adjective_lexicon() -> Lexicon {
    Lexicon::new("en", ["fast", "scalable", "user-friendly", "a lot", "soon"])
}

/// The operator-facing panel's rendered nudge (PRD FR-6.2/FR-5.11). No
/// production chrome for this exists yet in this workspace — `apps/desktop`
/// only has the `Nudge` TypeScript type this mirrors
/// (`apps/desktop/src/features/panel/nudge/types.ts`), no Rust-side
/// renderer — so this is the minimal shape carrying what that type
/// requires: a glanceable stub and the trigger reason FR-5.11 makes
/// mandatory, never optional.
#[derive(Debug, Clone, PartialEq)]
struct DisplayedNudge {
    stub: String,
    trigger_reason: String,
}

/// Renders exactly one lexicon match into the nudge the panel would show,
/// naming both the term that fired and the utterance it fired in so the
/// operator can calibrate trust in the system (FR-5.11's rationale: "without
/// a visible reason the operator cannot calibrate trust").
fn render_nudge(m: &LexiconMatch, utterance_text: &str) -> DisplayedNudge {
    DisplayedNudge {
        stub: format!("Quantify \"{}\"", m.term),
        trigger_reason: format!(
            "\"{}\" is an unquantified adjective in \"{}\" — ask them to put a number on it",
            m.matched_text, utterance_text
        ),
    }
}

/// A short, non-silent chunk of synthetic audio — content doesn't matter to
/// any stage of this pipeline, only that each frame is non-empty, which the
/// fake ASR backend enforces (`send_audio` rejects an empty frame).
fn synthetic_frame(len: usize) -> Vec<f32> {
    (0..len).map(|i| (i as f32 * 0.05).sin()).collect()
}

#[test]
fn capture_start_to_panel_nudge_for_a_vague_adjective_stays_inside_the_deterministic_latency_budget(
) {
    // Architecture §5's own figure for this exact path: no model call sits
    // between the lexicon scan and the rendered nudge.
    const DETERMINISTIC_PATH_BUDGET: Duration = Duration::from_millis(100);

    let start = Instant::now();

    // --- Capture starts -----------------------------------------------
    let mut pipeline = NormalizingPipeline::new();
    let mut segment_store = SegmentStore::new();
    let mut backend = ImmutablePartialFakeBackend::new();
    let stream_id: String = "stream-1".to_string();

    let mut retained_samples: Vec<i16> = Vec::new();
    let mut finals = Vec::new();

    // The fake backend's script finalises its first turn ("we need it
    // fast") on the second frame it receives (it interims on the first),
    // so two frames is exactly enough to observe one spoken, vague-adjective
    // utterance end to end.
    for _ in 0..2 {
        let raw = RawFrame::new(AudioFormat::new(16_000, 1), synthetic_frame(160));
        let normalized = pipeline.process(raw);
        retained_samples.extend(normalized.samples.iter().copied());

        backend
            .send_audio(&stream_id, &normalized.samples)
            .expect("a non-empty normalised frame is never rejected");
        for event in backend.poll_events() {
            if let TranscriptionEvent::Final(final_utterance) = event {
                finals.push(final_utterance);
            }
        }
    }

    assert_eq!(finals.len(), 1, "exactly one utterance should have finalised");
    let utterance = &finals[0];
    assert_eq!(utterance.text, "we need it fast", "the vague adjective must actually be spoken");

    // Capture retains the audio backing this utterance in memory only,
    // never on disk (FR-1.7) — the segment this nudge is ultimately traced
    // back to.
    let segment_ref = segment_store.insert(retained_samples);
    assert!(
        segment_store.get(&segment_ref).is_some(),
        "the utterance's audio must actually be retained, not merely referenced"
    );

    // --- Trigger gate ----------------------------------------------------
    // asr-live's `Token` and trigger-gate's `TaggedToken` are field-for-field
    // identical but belong to two crates with no dependency between them yet
    // (see this file's module doc) — the same local re-derivation this
    // crate's other e2e tests already use for `language`/`trigger-gate`.
    let tokens: Vec<TaggedToken> = utterance
        .tokens
        .iter()
        .map(|t| TaggedToken {
            text: t.text.clone(),
            confidence: t.confidence,
            lang: t.lang.clone(),
            lang_confidence: t.lang_confidence,
        })
        .collect();

    let mut router = LexiconRouter::new();
    router.register(vague_adjective_lexicon());
    let matches = router.run(&tokens, 0.6);

    // --- Panel -------------------------------------------------------
    let nudges: Vec<DisplayedNudge> =
        matches.iter().map(|m| render_nudge(m, &utterance.text)).collect();

    let elapsed = start.elapsed();

    assert_eq!(nudges.len(), 1, "the panel must display exactly one nudge");
    let nudge = &nudges[0];
    assert_eq!(nudge.stub, "Quantify \"fast\"");
    assert!(
        !nudge.trigger_reason.is_empty(),
        "FR-5.11: every surfaced nudge must carry its trigger reason"
    );
    assert!(
        nudge.trigger_reason.contains("fast"),
        "the trigger reason must name the term that actually fired it, not a generic message"
    );

    assert!(
        elapsed < DETERMINISTIC_PATH_BUDGET,
        "deterministic trigger path exceeded its latency budget: {elapsed:?} >= {DETERMINISTIC_PATH_BUDGET:?}"
    );
}
