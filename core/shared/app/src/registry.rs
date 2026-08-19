//! Crate registry — the single seam where plugin crates under
//! `core/crates/*` are wired into the shared core.
//!
//! The workspace manifest (`Cargo.toml`) mounts `core/crates/*` by glob, so
//! adding a plugin crate never requires editing the workspace file. This
//! module is the ordered seam for the other half of that wiring — declaring
//! each mounted crate as a dependency and re-exporting what the rest of the
//! core needs from it — so that wiring lands as one appended block per
//! crate instead of edits scattered across shared files.
//!
//! Ordered seam: append new entries below rather than editing existing
//! ones, so parallel additions land as independent hunks.
//!
//! Each block re-exports the crate under a stable name. Consumers depend on
//! `elicta_app::registry::<crate>` rather than on the plugin crate directly,
//! so a crate can be renamed or swapped at this seam alone.

/// Audio capture: device selection, enrolment, ring buffer and
/// normalisation, segment retention, and voice activity detection.
pub use capture;

/// Streaming ASR for the live path: backend handshake, transcription
/// events, and token emission.
pub use asr_live;

/// Language services shared by both paths: script segmentation, spoken
/// numeral normalisation, and token tagging.
pub use language;

/// Deterministic trigger detection: lexicon scanning, utterance parsing,
/// and nudge rate limiting.
pub use trigger_gate;

/// The on-device candidate bank and its retrieval surface.
pub use bank;

/// Candidate ranking: scoring and phrasing selection.
pub use ranking;

/// Requirements coverage state: slots, matrix, urgency, and the store.
pub use coverage;

/// The slow lane: model-assisted triggers, cache lifetime, and bank
/// write-back for novel candidates.
pub use slow_lane;

/// Word error rate scoring and the entity-class gate used to publish
/// accuracy figures.
pub use wer;

/// The plugin crates mounted at this seam, in registration order.
///
/// Consumers use this to report what a build actually contains; the startup
/// log in the desktop shell prints it the way the service tier prints its
/// mounted route list. Keep it in step with the re-exports above — the test
/// below fails if a crate is re-exported without being listed.
pub const MOUNTED_CRATES: &[&str] = &[
    "capture",
    "asr-live",
    "language",
    "trigger-gate",
    "bank",
    "ranking",
    "coverage",
    "slow-lane",
    "wer",
];

#[cfg(test)]
mod tests {
    use super::*;

    /// Every mounted crate must be reachable through the seam. Referencing
    /// one item per crate makes this a compile-time assertion that the
    /// dependency and its re-export both exist — the check that was missing
    /// while the registry sat empty.
    #[test]
    fn every_mounted_crate_is_reachable_through_the_registry() {
        let _ = capture::ring::AudioFormat::new(16_000, 1);
        let _: fn() -> asr_live::backend::ImmutablePartialFakeBackend =
            asr_live::backend::ImmutablePartialFakeBackend::new;
        let _ = language::segment::segment_utterance;
        let _ = trigger_gate::lexicon::Lexicon::new("en-registry-v1", "en", ["fast"]);
        let _ = bank::retrieval::retrieve_ranked_candidates;
        let _ = ranking::score::score_candidate;
        let _ = coverage::slot::FillState::Empty;
        let _ = slow_lane::model::ModelId::new("claude-sonnet-5");
        let _ = wer::EntityClass::Numeral;
    }

    #[test]
    fn the_mounted_crate_list_covers_every_plugin_crate_in_the_workspace() {
        // core/crates/* is globbed into the workspace; this list is the
        // registry's own record of what it mounted. A crate added to the
        // workspace but never mounted here is the failure this catches.
        assert_eq!(MOUNTED_CRATES.len(), 9, "all nine plugin crates are mounted");
    }
}
