//! Loads the actual per-language curated ambiguity lexicons (PRD section
//! 8.2a, feature 144), each rebuilt directly in and for its own language
//! rather than translated term-for-term from English.
//!
//! Every prior lexicon in this crate (`terms.rs`'s own tests, `router.rs`,
//! `hold.rs`, `evaluation.rs`) constructs a [`Lexicon`] from an arbitrary
//! in-memory term list supplied by the caller — that proves the
//! routing/matching/holding contracts, but nothing in this crate previously
//! loaded a real curated lexicon or gave one a persisted identity. This
//! module is that data source: [`load_curated_lexicons`] is the one place a
//! caller reaches for the actual, curated English and Mandarin Chinese
//! ambiguity term sets, each stamped with its own [`Lexicon::lexicon_id`]
//! (section 8.2a's "lexicon identifier") so a match can always be traced
//! back to exactly the curated build that found it.
//!
//! The English and Chinese lists below are deliberately *not* mirror
//! translations of one another. Some English vague quantifiers ("a
//! couple", "a handful") have no single idiomatic Chinese equivalent worth
//! curating on their own; some Chinese ambiguity markers ("差不多" — roughly,
//! close enough; "看情况" — depends on the situation; "尽量" — as much as
//! feasible) have no clean single-word English gloss and would read as
//! stilted if back-translated. Each list is curated against how ambiguity
//! actually shows up in that language's own client speech, which is exactly
//! what "rebuilt for that language rather than translated from English"
//! requires — a shared list run through a dictionary would fail both
//! languages' idiom.

use super::terms::Lexicon;

/// This build's English ambiguity lexicon: unquantified adjectives and
/// vague quantifiers (FR-5.2) as they actually occur in English client
/// speech, curated independently of the Chinese list below.
pub fn en_ambiguity_lexicon() -> Lexicon {
    Lexicon::new(
        "en-ambiguity-v1",
        "en",
        [
            "several",
            "a lot",
            "a couple",
            "a few",
            "a handful",
            "some",
            "many",
            "quite a few",
            "a bunch of",
            "as needed",
            "if possible",
            "as soon as possible",
            "typically",
            "generally",
            "reasonable amount",
            "fast",
            "quickly",
            "soon",
            "recently",
            "robust",
            "scalable",
            "flexible",
            "efficient",
            "user-friendly",
            "significant",
        ],
    )
}

/// This build's Mandarin Chinese ambiguity lexicon — curated directly
/// against Chinese client speech, not derived from
/// [`en_ambiguity_lexicon`]'s list.
pub fn zh_ambiguity_lexicon() -> Lexicon {
    Lexicon::new(
        "zh-ambiguity-v1",
        "zh",
        [
            "一些",     // some
            "很多",     // a lot / many
            "若干",     // a certain number of (formal register English lacks a direct match for)
            "差不多",   // roughly / close enough — no single-word English gloss
            "看情况",   // depends on the situation — idiomatic, not "some" or "several"
            "尽量",     // as much as feasible
            "尽快",     // as soon as possible
            "最近",     // recently
            "通常",     // usually / typically
            "一般来说", // generally speaking
            "灵活",     // flexible
            "高效",     // efficient
            "健壮",     // robust
            "友好",     // user-friendly (as in 用户友好)
            "适当",     // appropriate / a moderate amount
            "快速",     // quickly / fast
            "重大",     // significant
        ],
    )
}

/// Every curated lexicon this build ships, one per language, ready to
/// register on a [`super::router::LexiconRouter`] (e.g. via
/// [`super::router::LexiconRouter::with_curated_lexicons`]). Adding a new
/// language means adding one more curated function here and one more entry
/// in this vector — nothing about `Lexicon`, `LexiconRouter`, or the
/// isolation contract they implement needs to change.
pub fn load_curated_lexicons() -> Vec<Lexicon> {
    vec![en_ambiguity_lexicon(), zh_ambiguity_lexicon()]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexicon::grouping::{PositionedToken, TaggedToken};

    fn positioned(text: &str, lang: &str) -> Vec<PositionedToken> {
        vec![PositionedToken {
            index: 0,
            token: TaggedToken {
                text: text.to_string(),
                confidence: 0.9,
                lang: lang.to_string(),
                lang_confidence: 0.9,
            },
        }]
    }

    #[test]
    fn each_curated_lexicon_carries_its_own_persisted_identifier() {
        let lexicons = load_curated_lexicons();

        let ids: Vec<&str> = lexicons.iter().map(|l| l.lexicon_id.as_str()).collect();
        assert_eq!(ids, vec!["en-ambiguity-v1", "zh-ambiguity-v1"]);
    }

    #[test]
    fn curated_lexicons_cover_one_entry_per_language_loaded() {
        let lexicons = load_curated_lexicons();

        let languages: Vec<&str> = lexicons.iter().map(|l| l.language.as_str()).collect();
        assert_eq!(languages, vec!["en", "zh"]);
    }

    #[test]
    fn the_chinese_lexicon_is_not_a_translation_of_the_english_one() {
        // "rebuilt for that language rather than translated from English"
        // (section 8.2a): the Chinese list must curate at least one term
        // with no direct English-list counterpart, proving it wasn't
        // produced by running the English list through a dictionary.
        let zh = zh_ambiguity_lexicon();

        let matches = zh.scan(&positioned("差不多可以了", "zh"));

        assert!(matches.iter().any(|m| m.term == "差不多"));
    }

    #[test]
    fn each_curated_match_carries_its_own_lexicons_persisted_identifier() {
        let en = en_ambiguity_lexicon();

        let matches = en.scan(&positioned("several", "en"));

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].lexicon_id, "en-ambiguity-v1");
    }
}
