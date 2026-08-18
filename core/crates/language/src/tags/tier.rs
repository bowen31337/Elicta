use std::collections::HashMap;

/// Language support tiers (PRD §8.2a). Declared from most to least capable
/// so that `Ord` comparisons answer "did we drift into a *lower* tier?"
/// directly: `new_tier > old_tier` means less capability, not more.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LanguageTier {
    /// Deterministic live triggers, model triggers, coverage, artifacts.
    Tier1,
    /// Model-path triggers only. No sub-second nudges.
    Tier2,
    /// Transcript and artifacts only.
    Tier3,
}

impl LanguageTier {
    /// Operator-facing summary of what this tier keeps and loses (PRD §8.2a
    /// tier table), used to compose the tier-drift announcement (FR-2.23).
    pub fn capability_summary(&self) -> &'static str {
        match self {
            LanguageTier::Tier1 => {
                "full support: sub-second nudges, model-assisted nudges, coverage and artifacts"
            }
            LanguageTier::Tier2 => {
                "model-assisted nudges only, arriving in tens of seconds — no sub-second nudges"
            }
            LanguageTier::Tier3 => "transcript and artifacts only — no live nudges",
        }
    }
}

/// Maps a detected language to its support tier. Every language defaults to
/// Tier 2 (PRD §8.2a: "All other ASR-supported languages at Tier 2 by
/// default") except the launch Tier 1 set, and any language's tier can be
/// overridden — e.g. by automatic tier fallback when measured accuracy
/// misses its bar (NFR-5.8).
#[derive(Debug, Clone)]
pub struct LanguageTierTable {
    tiers: HashMap<String, LanguageTier>,
}

impl LanguageTierTable {
    /// Launch tiering (PRD §8.2a): English and Mandarin at Tier 1, every
    /// other language defaults to Tier 2.
    pub fn launch_default() -> Self {
        let mut table = LanguageTierTable { tiers: HashMap::new() };
        table.set_tier("en", LanguageTier::Tier1);
        table.set_tier("zh", LanguageTier::Tier1);
        table
    }

    /// The tier for `language`, matched on its BCP-47 primary subtag.
    /// Unlisted languages default to Tier 2.
    pub fn tier_for(&self, language: &str) -> LanguageTier {
        self.tiers
            .get(&primary_subtag(language))
            .copied()
            .unwrap_or(LanguageTier::Tier2)
    }

    /// Sets (or overrides) the tier for a language.
    pub fn set_tier(&mut self, language: &str, tier: LanguageTier) {
        self.tiers.insert(primary_subtag(language), tier);
    }
}

/// BCP-47 tags are compared on their primary subtag: "en-US" and "en" are
/// the same language for tiering purposes.
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
    fn launch_default_tiers_english_and_mandarin_at_tier_1() {
        let table = LanguageTierTable::launch_default();
        assert_eq!(table.tier_for("en"), LanguageTier::Tier1);
        assert_eq!(table.tier_for("zh"), LanguageTier::Tier1);
    }

    #[test]
    fn unlisted_language_defaults_to_tier_2() {
        let table = LanguageTierTable::launch_default();
        assert_eq!(table.tier_for("vi"), LanguageTier::Tier2);
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_do_not_affect_tiering() {
        let table = LanguageTierTable::launch_default();
        assert_eq!(table.tier_for("en-US"), LanguageTier::Tier1);
        assert_eq!(table.tier_for("zh-Hans"), LanguageTier::Tier1);
        assert_eq!(table.tier_for("EN"), LanguageTier::Tier1);
    }

    #[test]
    fn override_replaces_the_default_tier() {
        let mut table = LanguageTierTable::launch_default();
        table.set_tier("vi", LanguageTier::Tier3);
        assert_eq!(table.tier_for("vi"), LanguageTier::Tier3);
    }

    #[test]
    fn tier_ordering_treats_tier_1_as_most_capable() {
        assert!(LanguageTier::Tier1 < LanguageTier::Tier2);
        assert!(LanguageTier::Tier2 < LanguageTier::Tier3);
    }
}
