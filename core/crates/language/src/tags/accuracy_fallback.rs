use super::tier::{LanguageTier, LanguageTierTable};

/// Minimum acceptable accuracy for a language to be retained at a given
/// tier (PRD NFR-5.8). Accuracy is `1.0 - entity_weighted_wer` from the
/// NFR-5.1 scorer, so a language that reliably mangles numerals, proper
/// nouns, negations, or engagement vocabulary loses its tier even if its
/// plain word accuracy looks fine — the same weighting that drives the
/// published run figure decides whether a language keeps its capability
/// level.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AccuracyBar {
    /// Minimum accuracy to remain at Tier 1.
    pub tier1_min: f32,
    /// Minimum accuracy to remain at Tier 2.
    pub tier2_min: f32,
}

impl Default for AccuracyBar {
    /// Placeholder thresholds pending a labelled reference set (tracked
    /// alongside the `AlignmentWeights` defaults in the `wer` crate) — not
    /// PRD-mandated constants.
    fn default() -> Self {
        AccuracyBar { tier1_min: 0.85, tier2_min: 0.70 }
    }
}

impl AccuracyBar {
    /// The accuracy `tier` requires to be retained, or `None` for Tier 3:
    /// it is the floor tier, so there is nothing lower to fall back to and
    /// no bar to enforce.
    fn min_for(&self, tier: LanguageTier) -> Option<f32> {
        match tier {
            LanguageTier::Tier1 => Some(self.tier1_min),
            LanguageTier::Tier2 => Some(self.tier2_min),
            LanguageTier::Tier3 => None,
        }
    }
}

/// Operator-facing notification that a language's tier was automatically
/// dropped because measured accuracy missed its bar (PRD NFR-5.8).
#[derive(Debug, Clone, PartialEq)]
pub struct AccuracyFallbackNotice {
    pub language: String,
    pub from_tier: LanguageTier,
    pub to_tier: LanguageTier,
    pub measured_accuracy: f32,
    pub required_accuracy: f32,
}

impl AccuracyFallbackNotice {
    /// Operator-facing copy for the panel.
    pub fn message(&self) -> String {
        format!(
            "{} measured accuracy {:.1}% missed the {:?} bar of {:.1}% — automatically \
             falling back to {:?}: {}",
            self.language,
            self.measured_accuracy * 100.0,
            self.from_tier,
            self.required_accuracy * 100.0,
            self.to_tier,
            self.to_tier.capability_summary()
        )
    }
}

/// Watches measured per-language accuracy and automatically demotes a
/// language's tier the moment accuracy misses the bar for its *current*
/// tier (PRD NFR-5.8), always producing an [`AccuracyFallbackNotice`] to
/// surface to the operator.
///
/// This exists for the same reason [`super::tier_drift::TierDriftMonitor`]
/// always announces: a language quietly performing below its tier's bar
/// still produces plausible, well-formed transcript text, so nothing else
/// would surface the shortfall. Falling back must always be visible, never
/// silent.
#[derive(Debug, Clone, Copy, Default)]
pub struct AccuracyFallbackWatcher {
    bar: AccuracyBar,
}

impl AccuracyFallbackWatcher {
    pub fn new() -> Self {
        AccuracyFallbackWatcher::default()
    }

    /// Overrides the default accuracy bars.
    pub fn with_bar(mut self, bar: AccuracyBar) -> Self {
        self.bar = bar;
        self
    }

    /// Records a measured accuracy figure for `language` against `table`.
    /// If accuracy misses the bar for the language's current tier, the
    /// language is demoted exactly one tier in `table` and the resulting
    /// notice is returned. Meeting or exceeding the bar, or already sitting
    /// at the Tier 3 floor, returns `None` and leaves `table` untouched.
    pub fn observe(
        &self,
        table: &mut LanguageTierTable,
        language: &str,
        measured_accuracy: f32,
    ) -> Option<AccuracyFallbackNotice> {
        let current_tier = table.tier_for(language);
        let required_accuracy = self.bar.min_for(current_tier)?;

        if measured_accuracy >= required_accuracy {
            return None;
        }

        let to_tier = match current_tier {
            LanguageTier::Tier1 => LanguageTier::Tier2,
            LanguageTier::Tier2 => LanguageTier::Tier3,
            LanguageTier::Tier3 => return None,
        };

        table.set_tier(language, to_tier);

        Some(AccuracyFallbackNotice {
            language: language.to_string(),
            from_tier: current_tier,
            to_tier,
            measured_accuracy,
            required_accuracy,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accuracy_at_or_above_the_bar_does_not_fall_back() {
        let mut table = LanguageTierTable::launch_default();
        let watcher = AccuracyFallbackWatcher::new();

        assert_eq!(watcher.observe(&mut table, "en", 0.85), None);
        assert_eq!(watcher.observe(&mut table, "en", 0.99), None);
        assert_eq!(table.tier_for("en"), LanguageTier::Tier1);
    }

    #[test]
    fn accuracy_below_tier_1_bar_falls_back_to_tier_2_and_notifies() {
        let mut table = LanguageTierTable::launch_default();
        let watcher = AccuracyFallbackWatcher::new();

        let notice =
            watcher.observe(&mut table, "en", 0.5).expect("should fall back and notify");

        assert_eq!(notice.language, "en");
        assert_eq!(notice.from_tier, LanguageTier::Tier1);
        assert_eq!(notice.to_tier, LanguageTier::Tier2);
        assert_eq!(notice.measured_accuracy, 0.5);
        assert_eq!(table.tier_for("en"), LanguageTier::Tier2);
        assert!(notice.message().contains("falling back to Tier2"));
    }

    #[test]
    fn accuracy_below_tier_2_bar_falls_back_to_tier_3() {
        let mut table = LanguageTierTable::launch_default();
        table.set_tier("vi", LanguageTier::Tier2);
        let watcher = AccuracyFallbackWatcher::new();

        let notice =
            watcher.observe(&mut table, "vi", 0.4).expect("should fall back further");

        assert_eq!(notice.from_tier, LanguageTier::Tier2);
        assert_eq!(notice.to_tier, LanguageTier::Tier3);
        assert_eq!(table.tier_for("vi"), LanguageTier::Tier3);
    }

    #[test]
    fn tier_3_is_a_floor_with_no_further_fallback_or_notice() {
        let mut table = LanguageTierTable::launch_default();
        table.set_tier("xx", LanguageTier::Tier3);
        let watcher = AccuracyFallbackWatcher::new();

        assert_eq!(watcher.observe(&mut table, "xx", 0.0), None);
        assert_eq!(table.tier_for("xx"), LanguageTier::Tier3);
    }

    #[test]
    fn repeated_low_accuracy_only_falls_back_one_tier_at_a_time() {
        let mut table = LanguageTierTable::launch_default();
        let watcher = AccuracyFallbackWatcher::new();

        let first = watcher.observe(&mut table, "en", 0.1).expect("first fallback");
        assert_eq!(first.to_tier, LanguageTier::Tier2);

        // A second bad measurement now checks against the *new* Tier 2 bar,
        // and can still fall back further — this is not a one-shot check.
        let second = watcher.observe(&mut table, "en", 0.1).expect("second fallback");
        assert_eq!(second.from_tier, LanguageTier::Tier2);
        assert_eq!(second.to_tier, LanguageTier::Tier3);
    }

    #[test]
    fn custom_bar_overrides_default_thresholds() {
        let mut table = LanguageTierTable::launch_default();
        let watcher = AccuracyFallbackWatcher::new()
            .with_bar(AccuracyBar { tier1_min: 0.99, tier2_min: 0.70 });

        // Would pass the default 0.85 bar but misses this stricter one.
        let notice = watcher.observe(&mut table, "en", 0.9).expect("stricter bar should trip");
        assert_eq!(notice.to_tier, LanguageTier::Tier2);
    }

    #[test]
    fn notice_message_reports_language_and_percentages() {
        let mut table = LanguageTierTable::launch_default();
        let watcher = AccuracyFallbackWatcher::new();
        let notice = watcher.observe(&mut table, "en", 0.5).unwrap();

        let message = notice.message();
        assert!(message.contains("en"));
        assert!(message.contains("50.0%"));
        assert!(message.contains("85.0%"));
    }
}
