use std::collections::HashMap;

/// Stable identifier for a meeting participant, as assigned by the managed
/// capture vendor to one of its per-participant streams (PRD decision D4).
/// Mirrors `capture::enrol::stream_identity::ParticipantId` and
/// `asr_live::tokens::ParticipantId`; kept local rather than imported
/// because this crate does not depend on those crates yet — the field is
/// deliberately identical so re-pointing at the canonical type later is a
/// type-alias swap, not a rewrite.
pub type ParticipantId = String;

/// The language tag currently in force for one participant's stream.
#[derive(Debug, Clone, PartialEq)]
pub struct ParticipantLanguageTag {
    pub participant_id: ParticipantId,
    /// BCP-47 primary subtag, e.g. `"en"` or `"zh"`.
    pub language: String,
    pub confidence: f32,
}

/// Tags language independently for each participant's stream when the
/// capture mode provides separated audio per participant (PRD FR-2.15,
/// capture path documented at `capture::device::AudioSourceKind::ManagedParticipant`).
///
/// [`super::tier_drift::TierDriftMonitor`] tracks a single "dominant meeting
/// language" because it answers a meeting-wide question (has the whole
/// meeting's support tier dropped?). That collapses to the wrong answer for
/// language *tagging*: when managed capture hands the pipeline one already-
/// isolated stream per participant (the same separation
/// `asr_live::tokens::ParticipantTokenStreams` keeps one socket per
/// participant to preserve), a meeting with one English speaker and one
/// Mandarin speaker has two correct tags, not one dominant one. Collapsing
/// them onto a single tag would silently mislabel whichever participant
/// lost the vote — exactly the silent-misdetection failure mode PRD §8.2's
/// tiering design exists to avoid. This registry keeps one tag per
/// participant so neither stream's language is ever decided by the other's.
#[derive(Debug, Clone)]
pub struct ParticipantLanguageTags {
    /// Mirrors the tag-confidence gate already applied to the deterministic
    /// trigger tier (FR-2.22): an observation below this confidence is too
    /// unreliable to relabel a stream that already has a tag, or to seed a
    /// noisy first tag for a stream that doesn't.
    min_confidence: f32,
    current: HashMap<ParticipantId, ParticipantLanguageTag>,
}

impl Default for ParticipantLanguageTags {
    fn default() -> Self {
        ParticipantLanguageTags { min_confidence: 0.6, current: HashMap::new() }
    }
}

impl ParticipantLanguageTags {
    pub fn new() -> Self {
        ParticipantLanguageTags::default()
    }

    /// Overrides the default minimum tag confidence.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// The tag currently in force for `participant_id`'s stream, if that
    /// stream has produced at least one confident observation.
    pub fn tag_for(&self, participant_id: &str) -> Option<&ParticipantLanguageTag> {
        self.current.get(participant_id)
    }

    /// Number of participant streams currently carrying a language tag.
    pub fn tagged_stream_count(&self) -> usize {
        self.current.len()
    }

    /// Records an observed `language` for `participant_id`'s stream at
    /// `confidence`, matched on the BCP-47 primary subtag. Below
    /// `min_confidence`, the observation is dropped and the stream's
    /// existing tag (if any) is left untouched — a single noisy observation
    /// must never relabel or clear an already-tagged stream. At or above
    /// threshold, this participant's tag is set (or updated) independently
    /// of every other participant's, and the new tag is returned.
    pub fn observe(
        &mut self,
        participant_id: impl Into<ParticipantId>,
        language: &str,
        confidence: f32,
    ) -> Option<ParticipantLanguageTag> {
        if confidence < self.min_confidence {
            return None;
        }

        let tag = ParticipantLanguageTag {
            participant_id: participant_id.into(),
            language: primary_subtag(language),
            confidence,
        };

        self.current.insert(tag.participant_id.clone(), tag.clone());
        Some(tag)
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" tag a
/// stream the same way. Matches the convention already used by
/// `tags::tier::LanguageTierTable::tier_for` and `segment::group_by_language`;
/// duplicated locally rather than imported since neither exposes it.
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

    #[test]
    fn each_participant_stream_gets_its_own_tag() {
        let mut tags = ParticipantLanguageTags::new();

        tags.observe("alice", "en", 0.9);
        tags.observe("bob", "zh", 0.9);

        assert_eq!(tags.tag_for("alice").unwrap().language, "en");
        assert_eq!(tags.tag_for("bob").unwrap().language, "zh");
        assert_eq!(tags.tagged_stream_count(), 2);
    }

    #[test]
    fn observing_one_participant_does_not_affect_another() {
        let mut tags = ParticipantLanguageTags::new();

        tags.observe("alice", "en", 0.9);
        tags.observe("alice", "fr", 0.9);

        assert_eq!(tags.tag_for("alice").unwrap().language, "fr");
        assert_eq!(tags.tag_for("bob"), None);
    }

    #[test]
    fn untagged_participant_has_no_tag() {
        let tags = ParticipantLanguageTags::new();
        assert_eq!(tags.tag_for("alice"), None);
        assert_eq!(tags.tagged_stream_count(), 0);
    }

    #[test]
    fn low_confidence_observation_is_dropped() {
        let mut tags = ParticipantLanguageTags::new();
        assert_eq!(tags.observe("alice", "en", 0.2), None);
        assert_eq!(tags.tag_for("alice"), None);
    }

    #[test]
    fn low_confidence_observation_does_not_clear_an_existing_tag() {
        let mut tags = ParticipantLanguageTags::new();
        tags.observe("alice", "en", 0.9);

        assert_eq!(tags.observe("alice", "zh", 0.1), None);
        assert_eq!(tags.tag_for("alice").unwrap().language, "en");
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_to_primary_subtag() {
        let mut tags = ParticipantLanguageTags::new();
        tags.observe("alice", "en-US", 0.9);
        assert_eq!(tags.tag_for("alice").unwrap().language, "en");

        tags.observe("bob", "ZH-Hans", 0.9);
        assert_eq!(tags.tag_for("bob").unwrap().language, "zh");
    }

    #[test]
    fn custom_confidence_threshold_gates_observations() {
        let mut tags = ParticipantLanguageTags::new().with_min_confidence(0.95);
        assert_eq!(tags.observe("alice", "en", 0.9), None);
        assert!(tags.observe("alice", "en", 0.96).is_some());
    }

    #[test]
    fn a_later_confident_observation_updates_the_tag_and_returns_it() {
        let mut tags = ParticipantLanguageTags::new();
        tags.observe("alice", "en", 0.9);

        let updated = tags.observe("alice", "es", 0.85).expect("confident update returns tag");
        assert_eq!(updated.participant_id, "alice");
        assert_eq!(updated.language, "es");
        assert_eq!(updated.confidence, 0.85);
    }
}
