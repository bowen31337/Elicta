use super::tier::{LanguageTier, LanguageTierTable};

/// Severity for UI styling. Tier drops render as a warning (design system:
/// "Warning — amber: acoustic capture warning, tier drop announcement").
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnnouncementSeverity {
    Warning,
}

/// Explicit, operator-facing announcement that the meeting has drifted into
/// a lower support tier (PRD FR-2.23). [`TierDriftMonitor`] emits this once
/// per drift, not on every subsequent utterance while the meeting remains
/// in the new tier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TierAnnouncement {
    pub from_language: String,
    pub from_tier: LanguageTier,
    pub to_language: String,
    pub to_tier: LanguageTier,
    pub severity: AnnouncementSeverity,
}

impl TierAnnouncement {
    /// Operator-facing copy for the panel.
    pub fn message(&self) -> String {
        format!(
            "Meeting has drifted from {} to {} — {}",
            self.from_language,
            self.to_language,
            self.to_tier.capability_summary()
        )
    }
}

/// Tracks the dominant meeting language over time and raises an explicit
/// [`TierAnnouncement`] the moment the meeting drifts into a lower-capability
/// tier (PRD FR-2.23).
///
/// This exists because silent misdetection is the failure mode the tiering
/// design is built to avoid (PRD §8.2, rationale for FR-2.20-2.23): a
/// mislabelled or drifted language still produces plausible, well-formed
/// text, and nothing else raises an error. Detection must always be
/// visible, so a tier drop must always surface rather than degrade quietly.
pub struct TierDriftMonitor {
    table: LanguageTierTable,
    min_confidence: f32,
    current: Option<(String, LanguageTier)>,
}

impl TierDriftMonitor {
    pub fn new(table: LanguageTierTable) -> Self {
        TierDriftMonitor { table, min_confidence: 0.6, current: None }
    }

    /// Below this confidence, an observation is too unreliable to act on —
    /// mirrors the tag-confidence gate already applied to the deterministic
    /// trigger tier (FR-2.22), so a single noisy tag cannot raise or clear a
    /// tier announcement.
    pub fn with_min_confidence(mut self, min_confidence: f32) -> Self {
        self.min_confidence = min_confidence;
        self
    }

    /// The tier of the most recently observed (confident) dominant
    /// language, if any observation has been made yet.
    pub fn current_tier(&self) -> Option<LanguageTier> {
        self.current.as_ref().map(|(_, tier)| *tier)
    }

    /// Observes the dominant language for a newly finalised utterance.
    /// Returns `Some` exactly when the observation is confident enough to
    /// act on and represents a drift into a strictly lower tier than the
    /// previously observed language.
    pub fn observe(&mut self, language: &str, confidence: f32) -> Option<TierAnnouncement> {
        if confidence < self.min_confidence {
            return None;
        }

        let tier = self.table.tier_for(language);
        let announcement = self.current.as_ref().and_then(|(from_language, from_tier)| {
            (tier > *from_tier).then(|| TierAnnouncement {
                from_language: from_language.clone(),
                from_tier: *from_tier,
                to_language: language.to_string(),
                to_tier: tier,
                severity: AnnouncementSeverity::Warning,
            })
        });

        self.current = Some((language.to_string(), tier));
        announcement
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn monitor_with_default_tiers() -> TierDriftMonitor {
        TierDriftMonitor::new(LanguageTierTable::launch_default())
    }

    #[test]
    fn first_observation_never_announces() {
        let mut monitor = monitor_with_default_tiers();
        assert_eq!(monitor.observe("en", 0.95), None);
        assert_eq!(monitor.current_tier(), Some(LanguageTier::Tier1));
    }

    #[test]
    fn drift_from_tier_1_to_tier_2_announces() {
        let mut monitor = monitor_with_default_tiers();
        monitor.observe("en", 0.95);

        let announcement = monitor.observe("vi", 0.9).expect("should announce a tier drop");

        assert_eq!(announcement.from_language, "en");
        assert_eq!(announcement.from_tier, LanguageTier::Tier1);
        assert_eq!(announcement.to_language, "vi");
        assert_eq!(announcement.to_tier, LanguageTier::Tier2);
        assert_eq!(announcement.severity, AnnouncementSeverity::Warning);
        assert!(announcement.message().contains("model-assisted nudges only"));
    }

    #[test]
    fn switching_between_two_tier_1_languages_does_not_announce() {
        let mut monitor = monitor_with_default_tiers();
        monitor.observe("en", 0.95);
        assert_eq!(monitor.observe("zh", 0.95), None);
    }

    #[test]
    fn staying_in_the_same_lower_tier_only_announces_once() {
        let mut monitor = monitor_with_default_tiers();
        monitor.observe("en", 0.95);

        assert!(monitor.observe("vi", 0.9).is_some());
        assert_eq!(monitor.observe("vi", 0.9), None);
        assert_eq!(monitor.observe("vi", 0.9), None);
    }

    #[test]
    fn recovering_to_a_higher_tier_does_not_announce_but_updates_state() {
        let mut monitor = monitor_with_default_tiers();
        monitor.observe("en", 0.95);
        monitor.observe("vi", 0.9);

        assert_eq!(monitor.observe("en", 0.95), None);
        assert_eq!(monitor.current_tier(), Some(LanguageTier::Tier1));
    }

    #[test]
    fn dropping_further_from_tier_2_to_tier_3_announces_again() {
        let mut table = LanguageTierTable::launch_default();
        table.set_tier("xx", LanguageTier::Tier3);
        let mut monitor = TierDriftMonitor::new(table);
        monitor.observe("en", 0.95);
        monitor.observe("vi", 0.9);

        let announcement = monitor.observe("xx", 0.9).expect("further drop should announce");

        assert_eq!(announcement.from_tier, LanguageTier::Tier2);
        assert_eq!(announcement.to_tier, LanguageTier::Tier3);
    }

    #[test]
    fn low_confidence_observation_is_ignored_and_cannot_flap_state() {
        let mut monitor = monitor_with_default_tiers();
        monitor.observe("en", 0.95);

        assert_eq!(monitor.observe("vi", 0.2), None);
        assert_eq!(monitor.current_tier(), Some(LanguageTier::Tier1));
        assert!(monitor.observe("vi", 0.9).is_some());
    }
}
