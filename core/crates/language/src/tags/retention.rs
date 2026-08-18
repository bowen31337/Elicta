use std::collections::HashMap;

/// One translation produced from a [`RetainedUtterance`]'s original text.
#[derive(Debug, Clone, PartialEq)]
pub struct Translation {
    /// BCP-47 primary subtag of the translation's language, e.g. `"en"`.
    pub language: String,
    pub text: String,
}

/// An utterance exactly as spoken, plus every translation produced from it
/// (PRD FR-2.19: "Retain the original-language utterance alongside any
/// translation, permanently and inseparably").
///
/// The architecture's "original-language retention" invariant (§4: "a
/// translated utterance is stored as a translation *of* an original that is
/// never overwritten or discarded... translation is an added field, never a
/// replacement") is enforced here structurally rather than by caller
/// discipline: `original_language`/`original_text` are set once at
/// construction and no method on this type ever mutates or clears them.
/// [`Self::set_translation`] can only add or update an entry in the
/// translation map alongside the original — there is no way to construct a
/// `RetainedUtterance` without an original, and no way to end up with a
/// translation that has outlived (or replaced) the text it was translated
/// from. This is what "permanently and inseparably" means in practice: the
/// failure it exists to prevent is a scope dispute where a translated
/// citation is challenged and the client's actual original-language words
/// have already been discarded (R12), so a translated citation can render
/// both (PRD FR-8.7a) instead of only the translation.
#[derive(Debug, Clone, PartialEq)]
pub struct RetainedUtterance {
    original_language: String,
    original_text: String,
    /// First-translated order, so [`Self::translations`] lists them in a
    /// stable sequence rather than reshuffling on every update.
    order: Vec<String>,
    translations: HashMap<String, Translation>,
}

impl RetainedUtterance {
    /// Creates a retained utterance from its original-language text.
    /// `original_language` and `original_text` are fixed from this point on
    /// — nothing in this module's API can change or discard them once set.
    pub fn new(original_language: impl Into<String>, original_text: impl Into<String>) -> Self {
        let original_language = original_language.into();
        RetainedUtterance {
            original_language: primary_subtag(&original_language),
            original_text: original_text.into(),
            order: Vec::new(),
            translations: HashMap::new(),
        }
    }

    /// BCP-47 primary subtag of the language actually spoken.
    pub fn original_language(&self) -> &str {
        &self.original_language
    }

    /// The utterance exactly as spoken, before any translation.
    pub fn original_text(&self) -> &str {
        &self.original_text
    }

    /// Adds a translation into `language` (matched on its BCP-47 primary
    /// subtag), or updates that language's translation text if one already
    /// exists — e.g. a corrected re-translation. Either way this only ever
    /// touches the translation map: the original text and language are
    /// never read from or written through this method, and no other
    /// language's translation is affected.
    pub fn set_translation(
        &mut self,
        language: impl Into<String>,
        text: impl Into<String>,
    ) -> &Translation {
        let subtag = primary_subtag(&language.into());

        if !self.translations.contains_key(&subtag) {
            self.order.push(subtag.clone());
        }

        self.translations
            .insert(subtag.clone(), Translation { language: subtag.clone(), text: text.into() });

        self.translations.get(&subtag).expect("entry was just inserted")
    }

    /// The translation into `language`, if one has been produced.
    pub fn translation_for(&self, language: &str) -> Option<&Translation> {
        self.translations.get(&primary_subtag(language))
    }

    /// Every translation produced from this utterance so far, in
    /// first-translated order.
    pub fn translations(&self) -> Vec<&Translation> {
        self.order.iter().filter_map(|language| self.translations.get(language)).collect()
    }

    /// Whether a translation into `language` has been produced.
    pub fn has_translation(&self, language: &str) -> bool {
        self.translations.contains_key(&primary_subtag(language))
    }

    /// Number of distinct languages this utterance has been translated into.
    pub fn translation_count(&self) -> usize {
        self.translations.len()
    }

    /// The original text paired with its translation into `language`, for
    /// rendering a citation across a language boundary (PRD FR-8.7a) —
    /// exactly the pairing this type exists to keep from ever coming apart.
    /// `None` if no translation into `language` has been produced.
    pub fn paired_with(&self, language: &str) -> Option<(&str, &Translation)> {
        self.translation_for(language).map(|translation| (self.original_text.as_str(), translation))
    }
}

/// BCP-47 tags are matched on their primary subtag: "en-US" and "en" are the
/// same language here. Matches the convention already used by
/// `tags::tier::LanguageTierTable::tier_for` and sibling `tags` modules;
/// duplicated locally since none of them expose it.
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
    fn new_utterance_retains_its_original_language_and_text() {
        let utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");

        assert_eq!(utterance.original_language(), "es");
        assert_eq!(utterance.original_text(), "Necesitamos esto para el viernes");
        assert_eq!(utterance.translation_count(), 0);
    }

    #[test]
    fn adding_a_translation_does_not_change_the_original() {
        let mut utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");

        utterance.set_translation("en", "We need this by Friday");

        assert_eq!(utterance.original_language(), "es");
        assert_eq!(utterance.original_text(), "Necesitamos esto para el viernes");
        assert_eq!(utterance.translation_for("en").unwrap().text, "We need this by Friday");
    }

    #[test]
    fn multiple_translations_all_coexist_alongside_one_original() {
        let mut utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");

        utterance.set_translation("en", "We need this by Friday");
        utterance.set_translation("zh", "我们需要在星期五之前完成这个");

        assert_eq!(utterance.original_text(), "Necesitamos esto para el viernes");
        assert_eq!(utterance.translation_count(), 2);
        assert!(utterance.has_translation("en"));
        assert!(utterance.has_translation("zh"));
    }

    #[test]
    fn re_translating_the_same_language_updates_text_without_touching_the_original() {
        let mut utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");
        utterance.set_translation("en", "We need it Friday");

        let updated = utterance.set_translation("en", "We need this by Friday");

        assert_eq!(updated.text, "We need this by Friday");
        assert_eq!(utterance.translation_count(), 1);
        assert_eq!(utterance.original_text(), "Necesitamos esto para el viernes");
    }

    #[test]
    fn no_translation_for_a_language_that_was_never_produced() {
        let utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");

        assert_eq!(utterance.translation_for("en"), None);
        assert!(!utterance.has_translation("en"));
    }

    #[test]
    fn translations_are_listed_in_first_translated_order() {
        let mut utterance = RetainedUtterance::new("es", "texto original");
        utterance.set_translation("vi", "van ban");
        utterance.set_translation("en", "text");
        utterance.set_translation("zh", "文本");
        // Re-translating an already-translated language must not reorder it.
        utterance.set_translation("vi", "van ban moi");

        let languages: Vec<String> =
            utterance.translations().into_iter().map(|t| t.language.clone()).collect();
        assert_eq!(languages, vec!["vi", "en", "zh"]);
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_for_original_language() {
        let utterance = RetainedUtterance::new("EN-US", "we need this by Friday");
        assert_eq!(utterance.original_language(), "en");
    }

    #[test]
    fn bcp47_region_and_script_subtags_and_case_collapse_for_translations() {
        let mut utterance = RetainedUtterance::new("es", "texto original");
        utterance.set_translation("ZH-Hans", "文本");

        assert!(utterance.has_translation("zh"));
        assert_eq!(utterance.translation_for("zh-CN").unwrap().language, "zh");
    }

    #[test]
    fn paired_with_returns_the_original_and_the_requested_translation_together() {
        let mut utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");
        utterance.set_translation("en", "We need this by Friday");

        let (original, translation) = utterance.paired_with("en").expect("translation exists");
        assert_eq!(original, "Necesitamos esto para el viernes");
        assert_eq!(translation.text, "We need this by Friday");
        assert_eq!(translation.language, "en");
    }

    #[test]
    fn paired_with_is_none_when_no_translation_exists_for_that_language() {
        let utterance = RetainedUtterance::new("es", "Necesitamos esto para el viernes");
        assert_eq!(utterance.paired_with("en"), None);
    }

    #[test]
    fn an_untranslated_utterance_still_retains_its_original() {
        let utterance = RetainedUtterance::new("en", "we need this by Friday");

        assert_eq!(utterance.translation_count(), 0);
        assert_eq!(utterance.translations(), Vec::<&Translation>::new());
        assert_eq!(utterance.original_text(), "we need this by Friday");
    }
}
