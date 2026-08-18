use std::collections::HashMap;

use super::tier::{LanguageTier, LanguageTierTable};

/// One language currently shown in the live panel (PRD FR-2.20).
#[derive(Debug, Clone, PartialEq)]
pub struct DetectedLanguage {
    /// BCP-47 primary subtag, e.g. `"en"` or `"zh"`.
    pub language: String,
    pub tier: LanguageTier,
    /// Confidence of the most recent observation that updated this entry.
    pub confidence: f32,
}

/// Live, panel-facing registry of every language detected so far in the
/// meeting (PRD FR-2.20: "Display detected language(s) live in the panel").
///
/// This answers a different question than either of its siblings:
/// [`super::tier_drift::TierDriftMonitor`] tracks the single dominant
/// language to decide whether the *meeting* has drifted into a lower tier,
/// and [`super::participant::ParticipantLanguageTags`] tracks one tag per
/// participant stream to decide how to route each stream. Neither exposes
/// "every language detected during this meeting," which is exactly what the
/// panel must render live — a code-switched meeting with English and
/// Mandarin both in play should show both, continuously, not just whichever
/// one currently dominates or whichever participant last spoke. Per the
/// architecture's "silent misdetection" rationale (FR-2.20-2.23), a language
/// that was detected and then quietly drops off the panel is
/// indistinguishable from one that was never announced — so once a language
/// clears the confidence bar, it stays listed for the rest of the meeting.
#[derive(Debug, Clone)]
pub struct DetectedLanguagePanel {
    table: LanguageTierTable,
    /// Mirrors the tag-confidence gate applied elsewhere in `tags` (FR-2.22):
    /// a single noisy observation must never add a phantom language to the
    /// panel, nor silently overwrite an already-detected language's tier.
    min_confidence: f32,
    /// First-detected order, so the panel lists languages in a stable
    /// sequence rather than reshuffling on every observation.
    order: Vec<String>,
    entries: HashMap<String, DetectedLanguage>,
    /// BCP-47 primary subtag of the language currently active for the
    /// meeting: auto-detected until the user overrides it (FR-2.21).
    active: Option<String>,
    /// Once true, `active` was set by [`Self::override_language`] rather
    /// than auto-detection, and stays locked for the rest of the meeting.
    overridden: bool,
}

impl DetectedLanguagePanel {
    pub fn new(table: LanguageTierTable) -> Self {
        DetectedLanguagePanel {
            table,
            min_confidence: 0.6,
            order: Vec::new(),
            entries: HashMap::new(),
            active: None,
            overridden: false,
        }
    }

    /// Overrides the default minimum confidence to add or update an entry.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// Records an observed `language` at `confidence`, matched on its
    /// BCP-47 primary subtag. Below `min_confidence`, the observation is
    /// dropped and the panel is left untouched. At or above threshold, the
    /// language's entry is added (if new) or refreshed with the latest
    /// confidence and current tier (if already detected), and the resulting
    /// entry is returned. A language already on the panel is never removed
    /// by a later observation of a *different* language — every detected
    /// language remains visible for the rest of the meeting.
    ///
    /// Unless the user has already tapped an override (FR-2.21), the
    /// observed language also becomes the panel's active language. Once
    /// overridden, auto-detection keeps updating the visible list (a
    /// misdetected language must never be silently hidden either) but never
    /// moves `active` away from the user's choice.
    pub fn observe(&mut self, language: &str, confidence: f32) -> Option<&DetectedLanguage> {
        if confidence < self.min_confidence {
            return None;
        }

        let subtag = primary_subtag(language);
        let tier = self.table.tier_for(&subtag);

        if !self.entries.contains_key(&subtag) {
            self.order.push(subtag.clone());
        }

        self.entries.insert(
            subtag.clone(),
            DetectedLanguage { language: subtag.clone(), tier, confidence },
        );

        if !self.overridden {
            self.active = Some(subtag.clone());
        }

        self.entries.get(&subtag)
    }

    /// Every language detected so far in the meeting, in first-detected
    /// order, for the panel to render live.
    pub fn languages(&self) -> Vec<DetectedLanguage> {
        self.order.iter().filter_map(|language| self.entries.get(language).cloned()).collect()
    }

    /// Whether `language` (matched on its BCP-47 primary subtag) has been
    /// detected at or above the confidence threshold at any point in the
    /// meeting.
    pub fn is_detected(&self, language: &str) -> bool {
        self.entries.contains_key(&primary_subtag(language))
    }

    /// Number of distinct languages currently on the panel.
    pub fn detected_count(&self) -> usize {
        self.entries.len()
    }

    /// The language currently active for the meeting: the user's override
    /// once one has been tapped (FR-2.21), otherwise the most recent
    /// confident auto-detected observation. `None` before any observation
    /// or override has occurred.
    pub fn active_language(&self) -> Option<&DetectedLanguage> {
        self.active.as_ref().and_then(|language| self.entries.get(language))
    }

    /// Whether the active language is currently a user override rather than
    /// auto-detected.
    pub fn is_overridden(&self) -> bool {
        self.overridden
    }

    /// User taps `language` to override auto-detection for the rest of the
    /// meeting (PRD FR-2.21: "override the detected language with a single
    /// tap"). Takes effect immediately as the panel's active language,
    /// regardless of confidence, and — this is the feature's actual job —
    /// stays locked in: every subsequent call to [`Self::observe`] keeps
    /// updating the visible language list and their confidences, but can
    /// never move `active` away from this choice again for the rest of the
    /// meeting. If `language` was not already on the panel, it is added
    /// (at full confidence, since the user is asserting it directly) so the
    /// panel and the active language never disagree about what's in play.
    pub fn override_language(&mut self, language: &str) -> &DetectedLanguage {
        let subtag = primary_subtag(language);

        if !self.entries.contains_key(&subtag) {
            self.order.push(subtag.clone());
            let tier = self.table.tier_for(&subtag);
            self.entries.insert(
                subtag.clone(),
                DetectedLanguage { language: subtag.clone(), tier, confidence: 1.0 },
            );
        }

        self.active = Some(subtag.clone());
        self.overridden = true;

        self.entries.get(&subtag).expect("entry was just inserted or already present")
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" are the
/// same language for panel purposes. Matches the convention already used by
/// `tags::participant::ParticipantLanguageTags::observe` and
/// `tags::tier::LanguageTierTable::tier_for`; duplicated locally since
/// neither exposes it.
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

    fn panel_with_default_tiers() -> DetectedLanguagePanel {
        DetectedLanguagePanel::new(LanguageTierTable::launch_default())
    }

    #[test]
    fn a_confident_observation_adds_the_language_to_the_panel() {
        let mut panel = panel_with_default_tiers();

        let entry = panel.observe("en", 0.9).expect("confident observation");
        assert_eq!(entry.language, "en");
        assert_eq!(entry.tier, LanguageTier::Tier1);
        assert_eq!(entry.confidence, 0.9);
        assert!(panel.is_detected("en"));
        assert_eq!(panel.detected_count(), 1);
    }

    #[test]
    fn multiple_languages_all_stay_visible_at_once() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);
        panel.observe("zh", 0.85);

        let languages: Vec<String> = panel.languages().into_iter().map(|l| l.language).collect();
        assert_eq!(languages, vec!["en", "zh"]);
        assert_eq!(panel.detected_count(), 2);
    }

    #[test]
    fn languages_are_listed_in_first_detected_order() {
        let mut panel = panel_with_default_tiers();
        panel.observe("vi", 0.9);
        panel.observe("en", 0.9);
        panel.observe("zh", 0.9);
        // Re-observing an already-detected language must not reorder it.
        panel.observe("vi", 0.95);

        let languages: Vec<String> = panel.languages().into_iter().map(|l| l.language).collect();
        assert_eq!(languages, vec!["vi", "en", "zh"]);
    }

    #[test]
    fn low_confidence_observation_does_not_add_a_language() {
        let mut panel = panel_with_default_tiers();
        assert_eq!(panel.observe("en", 0.2), None);
        assert!(!panel.is_detected("en"));
        assert_eq!(panel.detected_count(), 0);
    }

    #[test]
    fn low_confidence_observation_does_not_remove_an_already_detected_language() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);

        assert_eq!(panel.observe("en", 0.1), None);
        assert!(panel.is_detected("en"));
        assert_eq!(panel.languages()[0].confidence, 0.9);
    }

    #[test]
    fn observing_one_language_never_removes_another() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);
        panel.observe("zh", 0.9);

        assert!(panel.is_detected("en"));
        assert!(panel.is_detected("zh"));
        assert_eq!(panel.detected_count(), 2);
    }

    #[test]
    fn a_later_confident_observation_refreshes_confidence_and_tier() {
        let mut table = LanguageTierTable::launch_default();
        table.set_tier("vi", LanguageTier::Tier3);
        let mut panel = DetectedLanguagePanel::new(table);

        panel.observe("vi", 0.7);
        let refreshed = panel.observe("vi", 0.95).expect("second confident observation");
        assert_eq!(refreshed.confidence, 0.95);
        assert_eq!(refreshed.tier, LanguageTier::Tier3);
        assert_eq!(panel.detected_count(), 1);
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_to_one_entry() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en-US", 0.9);
        panel.observe("EN", 0.95);

        assert_eq!(panel.detected_count(), 1);
        assert_eq!(panel.languages()[0].language, "en");
    }

    #[test]
    fn custom_confidence_threshold_gates_observations() {
        let mut panel = panel_with_default_tiers().with_min_confidence(0.95);
        assert_eq!(panel.observe("en", 0.9), None);
        assert!(panel.observe("en", 0.96).is_some());
    }

    #[test]
    fn empty_panel_has_no_languages() {
        let panel = panel_with_default_tiers();
        assert_eq!(panel.languages(), Vec::new());
        assert_eq!(panel.detected_count(), 0);
        assert!(!panel.is_detected("en"));
    }

    #[test]
    fn before_any_observation_or_override_there_is_no_active_language() {
        let panel = panel_with_default_tiers();
        assert_eq!(panel.active_language(), None);
        assert!(!panel.is_overridden());
    }

    #[test]
    fn auto_detection_sets_the_active_language_absent_an_override() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);
        assert_eq!(panel.active_language().unwrap().language, "en");

        panel.observe("zh", 0.9);
        assert_eq!(panel.active_language().unwrap().language, "zh");
        assert!(!panel.is_overridden());
    }

    #[test]
    fn a_single_tap_override_immediately_becomes_the_active_language() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);

        let overridden = panel.override_language("zh");
        assert_eq!(overridden.language, "zh");
        assert_eq!(panel.active_language().unwrap().language, "zh");
        assert!(panel.is_overridden());
    }

    #[test]
    fn override_persists_for_the_rest_of_the_meeting_despite_further_auto_detection() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);
        panel.override_language("zh");

        panel.observe("vi", 0.95);
        panel.observe("en", 0.99);

        assert_eq!(panel.active_language().unwrap().language, "zh");
        assert!(panel.is_overridden());
    }

    #[test]
    fn overriding_a_language_not_yet_detected_adds_it_to_the_panel() {
        let mut panel = panel_with_default_tiers();

        panel.override_language("vi");

        assert!(panel.is_detected("vi"));
        assert_eq!(panel.active_language().unwrap().language, "vi");
        assert_eq!(panel.active_language().unwrap().confidence, 1.0);
        assert_eq!(panel.detected_count(), 1);
    }

    #[test]
    fn override_does_not_remove_other_languages_from_the_panel() {
        let mut panel = panel_with_default_tiers();
        panel.observe("en", 0.9);
        panel.observe("zh", 0.9);

        panel.override_language("vi");

        let languages: Vec<String> = panel.languages().into_iter().map(|l| l.language).collect();
        assert_eq!(languages, vec!["en", "zh", "vi"]);
        assert_eq!(panel.detected_count(), 3);
    }

    #[test]
    fn a_later_override_replaces_an_earlier_one() {
        let mut panel = panel_with_default_tiers();
        panel.override_language("en");
        panel.override_language("zh");

        assert_eq!(panel.active_language().unwrap().language, "zh");
        assert!(panel.is_overridden());
    }

    #[test]
    fn overriding_with_a_bcp47_tag_collapses_to_the_primary_subtag() {
        let mut panel = panel_with_default_tiers();
        let overridden = panel.override_language("EN-US");

        assert_eq!(overridden.language, "en");
        assert_eq!(panel.active_language().unwrap().language, "en");
    }

    #[test]
    fn auto_detection_after_override_still_updates_the_visible_list() {
        let mut panel = panel_with_default_tiers();
        panel.override_language("en");

        panel.observe("vi", 0.9);

        assert!(panel.is_detected("vi"));
        assert_eq!(panel.active_language().unwrap().language, "en");
    }
}
