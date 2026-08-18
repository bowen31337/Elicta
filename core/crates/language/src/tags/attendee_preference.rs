use std::collections::HashMap;

/// Stable identifier for an attendee, persistent across every meeting in an
/// engagement — the `attendees.id` row, not the per-meeting vendor stream id
/// (`super::participant::ParticipantId`, which is only guaranteed stable for
/// the lifetime of one managed-capture session). Kept local rather than
/// imported since this crate has no dependency on the service's storage
/// layer; the field is deliberately a plain `String` so re-pointing at the
/// canonical id type later is a type-alias swap, not a rewrite.
pub type AttendeeId = String;

/// What has been learned about one attendee's language across an engagement
/// (PRD FR-2.16).
#[derive(Debug, Clone, PartialEq)]
pub struct AttendeeLanguagePreference {
    pub attendee_id: AttendeeId,
    /// BCP-47 primary subtag, e.g. `"en"` or `"zh"`.
    pub preferred_language: String,
    /// Total confident meeting-level observations recorded for this
    /// attendee across every language, not just `preferred_language`.
    pub meetings_observed: u32,
}

/// One attendee's history of confident per-meeting language observations,
/// most-recent tally kept per language rather than per-observation so the
/// registry stays `O(languages spoken)` per attendee, not
/// `O(meetings attended)`.
#[derive(Debug, Clone, Default)]
struct AttendeeRecord {
    /// `(language, meeting count)`, in first-observed order — this ordering
    /// is what makes tie-breaking deterministic (see `preferred`), matching
    /// the first-detected-order convention already used by
    /// `DetectedLanguagePanel::languages`.
    observations: Vec<(String, u32)>,
}

impl AttendeeRecord {
    fn record(&mut self, language: &str) {
        if let Some(entry) = self.observations.iter_mut().find(|(l, _)| l == language) {
            entry.1 += 1;
        } else {
            self.observations.push((language.to_string(), 1));
        }
    }

    /// The language with the most confident meetings behind it. Ties keep
    /// whichever language was already leading — since ties are only
    /// possible between a language observed earlier and one only just
    /// catching up, this means an established preference is never
    /// dislodged by a single later meeting in a different language, only by
    /// one that's been observed strictly *more* often. That mirrors why an
    /// engagement-level preference is worth learning in the first place: a
    /// one-off guest language in a later meeting is real, but it shouldn't
    /// silently overwrite a preference several prior meetings agreed on.
    fn preferred(&self) -> Option<(&str, u32)> {
        let mut leader: Option<&(String, u32)> = None;
        for entry in &self.observations {
            let is_new_leader = match leader {
                Some(current) => entry.1 > current.1,
                None => true,
            };
            if is_new_leader {
                leader = Some(entry);
            }
        }
        leader.map(|(language, count)| (language.as_str(), *count))
    }

    fn total_observed(&self) -> u32 {
        self.observations.iter().map(|(_, count)| count).sum()
    }
}

/// Learns each attendee's preferred language across an engagement (PRD
/// FR-2.16: "System learns per-attendee language preference across an
/// engagement, biasing that stream on later meetings") and biases later
/// confidence toward it.
///
/// This answers a different question than every sibling in this directory.
/// [`super::participant::ParticipantLanguageTags`] tags a participant
/// stream's language for the *current* meeting only — a fresh instance
/// starts from nothing at the top of every meeting, by design, since it
/// exists to catch code-switching within one session. FR-2.16 is the
/// opposite timescale: it is exactly the memory `ParticipantLanguageTags`
/// deliberately does not keep, carried across every meeting in an
/// engagement so a later meeting's detector already knows what to expect
/// from a returning attendee instead of re-learning it from zero every
/// time.
///
/// The registry only models the learning and the bias signal it produces;
/// it does not touch storage. The `attendees.preferred_language` column
/// already exists in the schema (`app_spec.txt` feature 10) — persisting a
/// learned [`AttendeeLanguagePreference`] there, and resolving which
/// `AttendeeId` a given meeting's `ParticipantId` stream belongs to, are
/// both jobs for whichever crate owns the live pipeline loop and the
/// engagement's storage layer, same boundary already drawn for
/// `RetainedUtterance` persistence in `retention.rs`.
#[derive(Debug, Clone)]
pub struct AttendeeLanguagePreferences {
    /// Mirrors the tag-confidence gate used throughout `tags` (FR-2.22): a
    /// single noisy meeting must never seed or shift a learned preference.
    min_confidence: f32,
    /// How much confidence a later observation gains when it matches the
    /// attendee's learned preference (see `bias_confidence`). Placeholder
    /// magnitude pending calibration against real engagement data, same
    /// caveat as `AccuracyBar`'s default thresholds — not PRD-mandated.
    bias_boost: f32,
    records: HashMap<AttendeeId, AttendeeRecord>,
}

impl Default for AttendeeLanguagePreferences {
    fn default() -> Self {
        AttendeeLanguagePreferences { min_confidence: 0.6, bias_boost: 0.15, records: HashMap::new() }
    }
}

impl AttendeeLanguagePreferences {
    pub fn new() -> Self {
        AttendeeLanguagePreferences::default()
    }

    /// Overrides the default minimum confidence to record an observation.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// Overrides the default bias boost applied by `bias_confidence`.
    pub fn with_bias_boost(mut self, bias_boost: f32) -> Self {
        self.bias_boost = bias_boost;
        self
    }

    /// Records that `attendee_id` was confidently tagged as `language` in a
    /// meeting, matched on the BCP-47 primary subtag. Below
    /// `min_confidence`, the observation is dropped and the attendee's
    /// learned preference (if any) is left untouched — a single noisy
    /// meeting must never seed or shift what's been learned. At or above
    /// threshold, this attendee's history gains one more confident meeting
    /// for `language`, the learned preference is recomputed, and the
    /// resulting preference is returned.
    pub fn observe_meeting(
        &mut self,
        attendee_id: impl Into<AttendeeId>,
        language: &str,
        confidence: f32,
    ) -> Option<AttendeeLanguagePreference> {
        if confidence < self.min_confidence {
            return None;
        }

        let attendee_id = attendee_id.into();
        let record = self.records.entry(attendee_id.clone()).or_default();
        record.record(&primary_subtag(language));

        let (preferred_language, _) =
            record.preferred().expect("an observation was just recorded");
        let meetings_observed = record.total_observed();

        Some(AttendeeLanguagePreference {
            attendee_id,
            preferred_language: preferred_language.to_string(),
            meetings_observed,
        })
    }

    /// The language currently in force for `attendee_id`, matched on its
    /// BCP-47 primary subtag, or `None` if no confident observation has
    /// ever been recorded for them.
    pub fn preferred_language(&self, attendee_id: &str) -> Option<&str> {
        self.records.get(attendee_id).and_then(AttendeeRecord::preferred).map(|(l, _)| l)
    }

    /// The full learned preference for `attendee_id` — the value that
    /// persists per attendee across the engagement (PRD FR-2.16) — or
    /// `None` if they have no confident observation on record yet.
    pub fn preference_for(&self, attendee_id: &str) -> Option<AttendeeLanguagePreference> {
        let record = self.records.get(attendee_id)?;
        let (preferred_language, _) = record.preferred()?;
        Some(AttendeeLanguagePreference {
            attendee_id: attendee_id.to_string(),
            preferred_language: preferred_language.to_string(),
            meetings_observed: record.total_observed(),
        })
    }

    /// Biases a later meeting's detection confidence toward what's been
    /// learned about `attendee_id` (PRD FR-2.16: "biasing that stream on
    /// later meetings"). If `language` (matched on its BCP-47 primary
    /// subtag) agrees with the attendee's learned preference, the observed
    /// `confidence` is boosted — closing the gap on a borderline detection
    /// that would otherwise miss a downstream confidence gate such as
    /// `ParticipantLanguageTags`'s. A `language` that disagrees with the
    /// learned preference is returned unchanged: biasing toward history must
    /// never suppress a confident contradicting signal, since an attendee
    /// (or a guest) genuinely speaking a different language in one meeting
    /// is a real event, not noise — the same silent-misdetection concern
    /// every confidence gate in this directory exists to guard against. An
    /// attendee with no learned preference yet is also returned unchanged,
    /// since there is nothing yet to bias toward.
    pub fn bias_confidence(&self, attendee_id: &str, language: &str, confidence: f32) -> f32 {
        match self.preferred_language(attendee_id) {
            Some(preferred) if preferred == primary_subtag(language) => {
                (confidence + self.bias_boost).min(1.0)
            }
            _ => confidence,
        }
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" are the
/// same language for preference-learning purposes. Matches the convention
/// already used by every sibling in this directory; duplicated locally since
/// none of them expose it.
fn primary_subtag(language: &str) -> String {
    language.split(['-', '_']).next().unwrap_or(language).to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attendee_with_no_observations_has_no_preference() {
        let preferences = AttendeeLanguagePreferences::new();
        assert_eq!(preferences.preferred_language("alice"), None);
        assert_eq!(preferences.preference_for("alice"), None);
    }

    #[test]
    fn a_single_confident_observation_becomes_the_preference() {
        let mut preferences = AttendeeLanguagePreferences::new();

        let preference =
            preferences.observe_meeting("alice", "en", 0.9).expect("confident observation");
        assert_eq!(preference.attendee_id, "alice");
        assert_eq!(preference.preferred_language, "en");
        assert_eq!(preference.meetings_observed, 1);
        assert_eq!(preferences.preferred_language("alice"), Some("en"));
    }

    #[test]
    fn low_confidence_observation_is_dropped() {
        let mut preferences = AttendeeLanguagePreferences::new();
        assert_eq!(preferences.observe_meeting("alice", "en", 0.2), None);
        assert_eq!(preferences.preferred_language("alice"), None);
    }

    #[test]
    fn low_confidence_observation_does_not_shift_an_existing_preference() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        assert_eq!(preferences.observe_meeting("alice", "zh", 0.1), None);
        assert_eq!(preferences.preferred_language("alice"), Some("en"));
    }

    #[test]
    fn repeating_the_same_language_increases_meetings_observed() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);
        preferences.observe_meeting("alice", "en", 0.95);

        let preference = preferences.preference_for("alice").unwrap();
        assert_eq!(preference.preferred_language, "en");
        assert_eq!(preference.meetings_observed, 2);
    }

    #[test]
    fn a_single_later_meeting_in_a_different_language_does_not_override_an_established_preference()
    {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);
        preferences.observe_meeting("alice", "en", 0.9);
        preferences.observe_meeting("alice", "en", 0.9);

        preferences.observe_meeting("alice", "fr", 0.95);

        assert_eq!(preferences.preferred_language("alice"), Some("en"));
    }

    #[test]
    fn a_language_overtaking_the_incumbent_becomes_the_new_preference() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        preferences.observe_meeting("alice", "fr", 0.9);
        preferences.observe_meeting("alice", "fr", 0.9);

        assert_eq!(preferences.preferred_language("alice"), Some("fr"));
    }

    #[test]
    fn a_tie_keeps_the_earlier_established_language() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);
        preferences.observe_meeting("alice", "fr", 0.9);

        assert_eq!(preferences.preferred_language("alice"), Some("en"));
    }

    #[test]
    fn each_attendee_is_tracked_independently() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);
        preferences.observe_meeting("bob", "zh", 0.9);

        assert_eq!(preferences.preferred_language("alice"), Some("en"));
        assert_eq!(preferences.preferred_language("bob"), Some("zh"));
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_to_primary_subtag() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en-US", 0.9);
        assert_eq!(preferences.preferred_language("alice"), Some("en"));

        preferences.observe_meeting("bob", "ZH-Hans", 0.9);
        assert_eq!(preferences.preferred_language("bob"), Some("zh"));
    }

    #[test]
    fn custom_confidence_threshold_gates_observations() {
        let mut preferences = AttendeeLanguagePreferences::new().with_min_confidence(0.95);
        assert_eq!(preferences.observe_meeting("alice", "en", 0.9), None);
        assert!(preferences.observe_meeting("alice", "en", 0.96).is_some());
    }

    #[test]
    fn bias_confidence_boosts_an_observation_matching_the_learned_preference() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        let biased = preferences.bias_confidence("alice", "en", 0.5);
        assert!(biased > 0.5);
        assert_eq!(biased, 0.65);
    }

    #[test]
    fn bias_confidence_leaves_a_contradicting_observation_unchanged() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        assert_eq!(preferences.bias_confidence("alice", "fr", 0.5), 0.5);
    }

    #[test]
    fn bias_confidence_leaves_an_unknown_attendee_unchanged() {
        let preferences = AttendeeLanguagePreferences::new();
        assert_eq!(preferences.bias_confidence("alice", "en", 0.5), 0.5);
    }

    #[test]
    fn bias_confidence_never_exceeds_one() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        assert_eq!(preferences.bias_confidence("alice", "en", 0.95), 1.0);
    }

    #[test]
    fn bias_confidence_matches_on_bcp47_primary_subtag() {
        let mut preferences = AttendeeLanguagePreferences::new();
        preferences.observe_meeting("alice", "en", 0.9);

        assert_eq!(preferences.bias_confidence("alice", "EN-US", 0.5), 0.65);
    }

    #[test]
    fn custom_bias_boost_overrides_the_default_magnitude() {
        let mut preferences = AttendeeLanguagePreferences::new().with_bias_boost(0.3);
        preferences.observe_meeting("alice", "en", 0.9);

        assert_eq!(preferences.bias_confidence("alice", "en", 0.5), 0.8);
    }
}
