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
            // -- Quantity hedges that read as numbers but are not ------------
            "不少",     // "quite a few" — sounds quantified, commits to nothing
            "大概",     // approximately
            "左右",     // "or so", trailing a number: 三百左右 = "about 300"
            "上下",     // same shape as 左右, used with counts and money
            "以内",     // "within", stated without the bound that matters
            // -- Commitment deferrals -----------------------------------------
            // The highest-value group and the one with no English counterpart
            // in the list above. Chinese business speech defers commitment
            // with verb reduplication, which sounds like agreement and is not:
            // 研究研究 ("we'll look into it") is a polite no in most rooms.
            "再说吧",   // "let's talk about it later"
            "到时候",   // "when the time comes"
            "研究研究", // "we'll study it" — reduplicated, softened, non-committal
            "考虑考虑", // "we'll consider it" — same construction
            "有机会",   // "if there's an opportunity"
            // -- Qualified agreement ------------------------------------------
            // These precede a "yes" and withdraw most of it. An operator who
            // does not hear the qualifier records a decision that was not made.
            "原则上",   // "in principle" — agreement with the exceptions unstated
            "基本上",   // "basically" — mostly true, with the remainder unsaid
            "理论上",   // "in theory"
            "应该没问题", // "should be fine" — the 应该 is doing the work
            // -- Unnamed scope --------------------------------------------------
            "相关的",   // "the relevant ones" — which ones is the requirement
            "有关方面", // "the parties concerned" — names nobody
            "各方面",   // "all aspects"
            "等等",     // "and so on" — ends a list before it is complete
        ],
    )
}

/// The ambiguity categories this product recognises, and how each language's
/// curated list covers them.
///
/// Journey 4 left an honest open question: an evasive answer Elicta catches in
/// English may not be catchable in Mandarin at all. Left as prose that stayed
/// an open question indefinitely, because nothing measured it. This is the
/// measurement — the categories are enumerated, each language's coverage is
/// asserted below, and a category one language cannot cover is named here
/// rather than discovered in a meeting.
///
/// The finding, as of `zh-ambiguity-v1`: coverage is not symmetric, and that
/// is correct rather than a deficiency. English carries vague *quantifiers*
/// that Chinese expresses with measure words no lexicon can enumerate; Chinese
/// carries a whole commitment-deferral category (verb reduplication:
/// 研究研究, 考虑考虑) that English has no lexical equivalent for at all — the
/// English equivalent is tone, which a term list cannot see. Each list is
/// stronger than the other somewhere.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AmbiguityCategory {
    /// Amounts stated without a number: "several", 不少.
    UnquantifiedAmount,
    /// Adjectives asserting a property without a threshold: "fast", 高效.
    UnquantifiedProperty,
    /// Time stated without a date: "soon", 尽快.
    UnquantifiedTime,
    /// Agreement withdrawn by a qualifier: 原则上, 基本上.
    QualifiedAgreement,
    /// Commitment deferred to an unnamed later: 研究研究, 再说吧.
    ///
    /// English has no lexical form of this. It is carried by intonation and
    /// hedged modals, which a term lexicon cannot detect — so this category is
    /// deliberately Chinese-only, and the English list does not pretend to it.
    DeferredCommitment,
    /// Scope named without members: "the relevant systems", 相关的.
    UnnamedScope,
}

/// One example term per category, per language — `None` where the language has
/// no lexical form of that category at all.
pub fn category_coverage(language: &str) -> Vec<(AmbiguityCategory, Option<&'static str>)> {
    match language {
        "en" => vec![
            (AmbiguityCategory::UnquantifiedAmount, Some("several")),
            (AmbiguityCategory::UnquantifiedProperty, Some("fast")),
            (AmbiguityCategory::UnquantifiedTime, Some("soon")),
            (AmbiguityCategory::QualifiedAgreement, Some("typically")),
            // Named as absent rather than filled with an approximation: a
            // near-miss term here would fire on ordinary speech and cost the
            // M2 gate, which allows zero embarrassing suggestions.
            (AmbiguityCategory::DeferredCommitment, None),
            (AmbiguityCategory::UnnamedScope, Some("as needed")),
        ],
        "zh" => vec![
            (AmbiguityCategory::UnquantifiedAmount, Some("不少")),
            (AmbiguityCategory::UnquantifiedProperty, Some("高效")),
            (AmbiguityCategory::UnquantifiedTime, Some("尽快")),
            (AmbiguityCategory::QualifiedAgreement, Some("原则上")),
            (AmbiguityCategory::DeferredCommitment, Some("研究研究")),
            (AmbiguityCategory::UnnamedScope, Some("相关的")),
        ],
        _ => Vec::new(),
    }
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
    fn the_chinese_list_catches_deferred_commitment_which_english_cannot() {
        // The highest-value Mandarin category and the clearest asymmetry:
        // 研究研究 sounds like agreement and is a polite no. An operator who
        // records it as a decision has recorded the opposite of what happened.
        let zh = zh_ambiguity_lexicon();

        for deferral in ["研究研究", "考虑考虑", "再说吧", "到时候"] {
            let matches = zh.scan(&positioned(deferral, "zh"));
            assert!(
                matches.iter().any(|m| m.term == deferral),
                "{deferral} is not caught"
            );
        }
    }

    #[test]
    fn qualified_agreement_is_caught_before_it_is_recorded_as_a_decision() {
        let zh = zh_ambiguity_lexicon();

        let matches = zh.scan(&positioned("原则上应该没问题", "zh"));

        assert!(matches.iter().any(|m| m.term == "原则上"));
        assert!(matches.iter().any(|m| m.term == "应该没问题"));
    }

    #[test]
    fn a_number_with_a_trailing_hedge_is_still_ambiguous() {
        // 三百左右 is "about 300" — it reads as quantified and is not, which
        // is exactly the failure the whole trigger exists to catch.
        let zh = zh_ambiguity_lexicon();

        assert!(zh
            .scan(&positioned("我们每天大概三百左右", "zh"))
            .iter()
            .any(|m| m.term == "左右"));
    }

    #[test]
    fn every_category_is_answered_for_both_languages() {
        // The measurement that replaces journey 4's open question: each
        // category is either covered or explicitly named as uncoverable, and
        // no category is silently absent from a language's list.
        for language in ["en", "zh"] {
            let coverage = category_coverage(language);
            assert_eq!(coverage.len(), 6, "{language} does not answer every category");

            for (category, example) in coverage {
                if let Some(term) = example {
                    let lexicon = if language == "en" {
                        en_ambiguity_lexicon()
                    } else {
                        zh_ambiguity_lexicon()
                    };
                    assert!(
                        lexicon.scan(&positioned(term, language)).iter().any(|m| m.term == term),
                        "{language} claims {category:?} via {term}, which its lexicon does not contain"
                    );
                }
            }
        }
    }

    #[test]
    fn the_one_category_english_cannot_cover_is_named_rather_than_faked() {
        // Filling this with a near-miss term would fire on ordinary English
        // and cost the M2 gate, which allows zero embarrassing suggestions.
        let english_gaps: Vec<_> = category_coverage("en")
            .into_iter()
            .filter(|(_, example)| example.is_none())
            .map(|(category, _)| category)
            .collect();

        assert_eq!(english_gaps, vec![AmbiguityCategory::DeferredCommitment]);
        // And Chinese covers it, so the asymmetry runs in the direction the
        // documentation claims.
        assert!(category_coverage("zh")
            .into_iter()
            .all(|(_, example)| example.is_some()));
    }

    #[test]
    fn an_unknown_language_claims_no_coverage() {
        assert!(category_coverage("fr").is_empty());
    }

    #[test]
    fn each_curated_match_carries_its_own_lexicons_persisted_identifier() {
        let en = en_ambiguity_lexicon();

        let matches = en.scan(&positioned("several", "en"));

        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].lexicon_id, "en-ambiguity-v1");
    }
}
