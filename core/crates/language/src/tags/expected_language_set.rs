/// The engagement-scoped set of languages expected in a meeting, derived
/// from client context (PRD FR-2.14: "Constrain detection to an
/// engagement-scoped expected-language set, derived from client context").
/// The derivation itself — scanning client organisation/sector/commercial
/// context for language signals — lives in the service layer
/// (`apps/service/.../vocabulary/language.py`'s `derive_expected_languages`,
/// persisted as `engagements.expected_languages`); this crate has no
/// engagement-context or storage layer and only consumes the resulting set,
/// same cross-layer boundary this directory's `HANDOFF.md` draws for every
/// other engagement-scoped concern (e.g. `AttendeeLanguagePreferences`'s
/// `attendees.preferred_language` column).
///
/// This type answers a narrower question than that derivation: given the
/// set, how should it act on detection. Per FR-2.14's own wording —
/// "Languages outside the set still transcribe, but rank lower" — the
/// answer is never exclusion. `contains` and `rank` are the only two
/// operations this type exposes, and neither can drop a language: `rank`
/// always returns exactly one [`RankedLanguage`] per input candidate,
/// outside-set or not.
#[derive(Debug, Clone)]
pub struct ExpectedLanguageSet {
    /// BCP-47 primary subtags, deduplicated, first-seen order (order is not
    /// load-bearing for `contains`/`rank`, but keeps `Debug` output and
    /// iteration deterministic, matching `DetectedLanguagePanel`'s `order`
    /// convention).
    languages: Vec<String>,
    /// How much a language outside the set is penalized when computing
    /// `rank`, relative to its raw confidence. Placeholder magnitude pending
    /// calibration against real engagement data, same caveat already
    /// attached to `AttendeeLanguagePreferences::bias_boost` and
    /// `AccuracyBar`'s thresholds — not PRD-mandated.
    outside_penalty: f32,
}

impl Default for ExpectedLanguageSet {
    fn default() -> Self {
        ExpectedLanguageSet { languages: Vec::new(), outside_penalty: 0.15 }
    }
}

/// One detection candidate after constraining to an [`ExpectedLanguageSet`]
/// (PRD FR-2.14).
#[derive(Debug, Clone, PartialEq)]
pub struct RankedLanguage {
    /// BCP-47 primary subtag.
    pub language: String,
    /// Confidence exactly as observed. Constraining never rewrites this —
    /// only `rank`, the derived value used to prioritize candidates, is
    /// touched — so a caller can always recover what was actually detected.
    pub confidence: f32,
    /// Whether `language` is in the engagement's expected set.
    pub in_expected_set: bool,
    /// The prioritization score: equal to `confidence` for an expected-set
    /// language, `confidence` minus the outside penalty otherwise. Higher
    /// ranks first. This is what makes "ranking outside languages lower"
    /// concrete — a lower `rank` value, never a dropped candidate.
    pub rank: f32,
}

impl ExpectedLanguageSet {
    /// Builds the set from BCP-47 tags, matched and deduplicated on their
    /// primary subtag.
    pub fn new(languages: impl IntoIterator<Item = impl AsRef<str>>) -> Self {
        let mut set = ExpectedLanguageSet::default();
        for language in languages {
            let subtag = primary_subtag(language.as_ref());
            if !set.languages.contains(&subtag) {
                set.languages.push(subtag);
            }
        }
        set
    }

    /// Overrides the default outside-set rank penalty.
    pub fn with_outside_penalty(mut self, outside_penalty: f32) -> Self {
        self.outside_penalty = outside_penalty;
        self
    }

    /// Whether `language` (matched on its BCP-47 primary subtag) is in the
    /// engagement's expected set.
    pub fn contains(&self, language: &str) -> bool {
        self.languages.iter().any(|l| l == &primary_subtag(language))
    }

    /// Constrains detection to this set (PRD FR-2.14). Every candidate in
    /// `candidates` is kept — an outside-set language still transcribes and
    /// still comes back here, exactly once — but each is given a `rank`
    /// that keeps an outside-set language from out-ranking an expected one
    /// purely for having equal or marginally higher raw confidence. Returned
    /// sorted by `rank` descending (highest-priority language first); ties
    /// keep the candidates' original relative order (stable sort), matching
    /// every other tie-breaking convention in this directory.
    pub fn rank(&self, candidates: &[(String, f32)]) -> Vec<RankedLanguage> {
        let mut ranked: Vec<RankedLanguage> = candidates
            .iter()
            .map(|(language, confidence)| {
                let in_expected_set = self.contains(language);
                let rank =
                    if in_expected_set { *confidence } else { confidence - self.outside_penalty };
                RankedLanguage {
                    language: primary_subtag(language),
                    confidence: *confidence,
                    in_expected_set,
                    rank,
                }
            })
            .collect();

        ranked.sort_by(|a, b| b.rank.partial_cmp(&a.rank).unwrap_or(std::cmp::Ordering::Equal));
        ranked
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" are the
/// same language for constraint purposes. Matches the convention already
/// used by every sibling in this directory; duplicated locally since none of
/// them expose it.
fn primary_subtag(language: &str) -> String {
    language.split(['-', '_']).next().unwrap_or(language).to_ascii_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(language: &str, confidence: f32) -> (String, f32) {
        (language.to_string(), confidence)
    }

    #[test]
    fn a_language_in_the_set_is_contained() {
        let set = ExpectedLanguageSet::new(["en", "zh"]);
        assert!(set.contains("en"));
        assert!(set.contains("zh"));
    }

    #[test]
    fn a_language_outside_the_set_is_not_contained() {
        let set = ExpectedLanguageSet::new(["en"]);
        assert!(!set.contains("fr"));
    }

    #[test]
    fn an_empty_set_contains_nothing() {
        let set = ExpectedLanguageSet::new(Vec::<&str>::new());
        assert!(!set.contains("en"));
    }

    #[test]
    fn contains_matches_on_bcp47_primary_subtag() {
        let set = ExpectedLanguageSet::new(["en"]);
        assert!(set.contains("en-US"));
        assert!(set.contains("EN"));
    }

    #[test]
    fn duplicate_languages_in_the_input_are_deduplicated() {
        let set = ExpectedLanguageSet::new(["en", "en-US", "EN"]);
        assert!(set.contains("en"));
    }

    #[test]
    fn an_outside_set_language_emits_a_lower_rank_than_an_expected_one_at_equal_confidence() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("en", 0.7), candidate("fr", 0.7)]);

        let en = ranked.iter().find(|r| r.language == "en").unwrap();
        let fr = ranked.iter().find(|r| r.language == "fr").unwrap();
        assert!(fr.rank < en.rank);
        assert!(en.in_expected_set);
        assert!(!fr.in_expected_set);
    }

    #[test]
    fn ranking_never_excludes_an_outside_set_language() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("fr", 0.9)]);

        assert_eq!(ranked.len(), 1);
        assert_eq!(ranked[0].language, "fr");
        assert!(!ranked[0].in_expected_set);
    }

    #[test]
    fn ranking_preserves_the_raw_confidence_of_every_candidate() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("en", 0.8), candidate("fr", 0.5)]);

        let en = ranked.iter().find(|r| r.language == "en").unwrap();
        let fr = ranked.iter().find(|r| r.language == "fr").unwrap();
        assert_eq!(en.confidence, 0.8);
        assert_eq!(fr.confidence, 0.5);
    }

    #[test]
    fn ranked_output_sorts_expected_set_languages_ahead_of_outside_ones() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("fr", 0.7), candidate("en", 0.65)]);

        assert_eq!(ranked[0].language, "en");
        assert_eq!(ranked[1].language, "fr");
    }

    #[test]
    fn a_sufficiently_higher_outside_confidence_can_still_outrank_an_expected_language() {
        // The constraint biases the candidate set; it does not hard-veto a
        // dramatically stronger outside-set signal, matching FR-2.14's
        // "still transcribe" framing rather than a hard exclusion/override.
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("en", 0.2), candidate("fr", 0.9)]);

        assert_eq!(ranked[0].language, "fr");
    }

    #[test]
    fn multiple_outside_set_languages_still_rank_relative_to_each_other_by_confidence() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("fr", 0.5), candidate("vi", 0.8)]);

        assert_eq!(ranked[0].language, "vi");
        assert_eq!(ranked[1].language, "fr");
    }

    #[test]
    fn a_tie_in_rank_keeps_the_original_relative_order() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("en", 0.5), candidate("zh", 0.5)]);

        assert_eq!(ranked[0].language, "en");
        assert_eq!(ranked[1].language, "zh");
    }

    #[test]
    fn rank_matches_candidates_on_bcp47_primary_subtag() {
        let set = ExpectedLanguageSet::new(["en"]);
        let ranked = set.rank(&[candidate("EN-US", 0.7)]);

        assert_eq!(ranked[0].language, "en");
        assert!(ranked[0].in_expected_set);
    }

    #[test]
    fn custom_outside_penalty_overrides_the_default_magnitude() {
        let set = ExpectedLanguageSet::new(["en"]).with_outside_penalty(0.3);
        let ranked = set.rank(&[candidate("fr", 0.7)]);

        assert!((ranked[0].rank - 0.4).abs() < 1e-6);
    }

    #[test]
    fn an_empty_expected_set_still_ranks_every_candidate_without_excluding_any() {
        let set = ExpectedLanguageSet::new(Vec::<&str>::new());
        let ranked = set.rank(&[candidate("en", 0.7), candidate("fr", 0.6)]);

        assert_eq!(ranked.len(), 2);
        assert!(ranked.iter().all(|r| !r.in_expected_set));
    }

    #[test]
    fn ranking_no_candidates_returns_an_empty_list() {
        let set = ExpectedLanguageSet::new(["en"]);
        assert_eq!(set.rank(&[]), Vec::new());
    }
}
