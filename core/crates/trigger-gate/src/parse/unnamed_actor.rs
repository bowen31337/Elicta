//! Detects English unnamed-actor clauses (PRD FR-5.3, architecture §3.5:
//! "Unnamed actor — Dependency parse; passive constructions and agentless
//! clauses").
//!
//! A real dependency parse would recover the grammatical subject of a
//! clause and check whether it names an actor at all. This crate has no
//! dependency-parsing library available (no crate in this workspace parses
//! English syntax trees — see the workspace root `Cargo.toml`), so
//! [`find_agentless_clauses`] approximates the one surface pattern FR-5.3
//! actually asks for — passive voice with no `by <agent>` phrase — as a
//! local two-token scan: a form of "to be" immediately followed by a past
//! participle, with no `by` within a short lookahead. This mirrors
//! `lexicon::terms::Lexicon::scan`'s own relationship to the Aho-Corasick
//! engine FR-5.2 eventually wants: a plain scan standing in for the
//! named technique over the same output contract, replaceable without
//! changing what downstream code sees.
//!
//! Known gaps this local scan does not cover, left for a real parse:
//! adverbs or negation between the be-verb and the participle ("was not
//! reviewed", "was quickly reviewed") break the required adjacency, and a
//! bare `-ed` adjective ("was interested") can be mistaken for a passive
//! participle. Both trade recall or precision for running with no NLP
//! dependency at all — acceptable for FR-5.3's P0 bar today, not a design
//! deemed final.
//!
//! This heuristic is disabled entirely for [`PRO_DROP_LANGUAGES`] (PRD
//! §8.2a): it is English-derived and has no way to distinguish a genuine
//! agentless clause from a pro-drop language's ordinary, grammatical dropped
//! subject, so porting it as-is would fire on a large fraction of
//! well-formed sentences in those languages rather than degrade gracefully.

use std::ops::Range;

use crate::lexicon::TaggedToken;

use super::event::{TriggerEvent, UtteranceId};
use super::gate::gate_span_confidence;

/// Finite forms of "to be" a passive clause opens with.
const BE_FORMS: &[&str] = &["am", "is", "are", "was", "were", "be", "been", "being"];

/// Past participles common enough in meeting speech to misclassify as
/// ordinary verbs if only the regular `-ed` suffix were checked.
const IRREGULAR_PAST_PARTICIPLES: &[&str] = &[
    "done",
    "given",
    "shown",
    "known",
    "made",
    "sent",
    "held",
    "written",
    "spoken",
    "broken",
    "chosen",
    "taken",
    "seen",
    "gone",
    "found",
    "built",
    "sold",
    "told",
    "kept",
    "left",
    "brought",
    "bought",
    "caught",
    "taught",
    "thought",
    "sought",
    "understood",
    "meant",
    "spent",
    "lost",
    "set",
    "put",
    "cut",
    "run",
    "become",
    "begun",
    "drawn",
    "grown",
    "thrown",
    "sworn",
    "torn",
    "worn",
    "born",
    "frozen",
    "stolen",
    "woken",
    "driven",
    "ridden",
    "risen",
    "bitten",
    "hidden",
    "forgotten",
    "gotten",
    "eaten",
    "beaten",
    "fallen",
];

/// How many tokens past a matched participle to search for an explicit `by
/// <agent>` phrase before concluding the clause names no actor at all.
/// Bounded rather than scanning to the end of the utterance so an
/// unrelated, later "by" elsewhere in a long sentence cannot retroactively
/// clear an actually-agentless clause.
const AGENT_LOOKAHEAD: usize = 3;

/// BCP-47 primary subtags of languages that drop grammatical subjects as
/// ordinary, well-formed grammar (PRD §8.2a; architecture §3.5: "Chinese,
/// Japanese, Korean and others omit subjects as ordinary grammar rather than
/// as evasion"). This English-derived agentless-clause heuristic has no
/// notion of a dropped-but-implied subject, so a pro-drop sentence's every
/// ordinary subjectless clause would otherwise misfire it — "not a precision
/// degradation but a precision collapse" per the architecture doc. Named
/// explicitly rather than inferred from a broader "is this pro-drop"
/// classifier: only the languages the source docs actually call out.
const PRO_DROP_LANGUAGES: &[&str] = &["zh", "ja", "ko"];

/// Whether `lang` (a BCP-47 tag, possibly with a region/script subtag like
/// `"zh-Hans"`) names a language in [`PRO_DROP_LANGUAGES`]. Compares only the
/// primary subtag, the same granularity `lexicon::group_by_language` groups
/// on, so `"zh-Hans"` and `"zh-TW"` are both recognised as `"zh"`.
fn is_pro_drop_language(lang: &str) -> bool {
    let primary = lang.split(['-', '_']).next().unwrap_or(lang);
    PRO_DROP_LANGUAGES
        .iter()
        .any(|candidate| candidate.eq_ignore_ascii_case(primary))
}

fn is_be_form(word: &str) -> bool {
    BE_FORMS.contains(&word.to_lowercase().as_str())
}

fn is_past_participle(word: &str) -> bool {
    let lower = word.to_lowercase();
    IRREGULAR_PAST_PARTICIPLES.contains(&lower.as_str()) || is_regular_past_participle(&lower)
}

fn is_regular_past_participle(lower: &str) -> bool {
    lower.len() > 2 && lower.ends_with("ed")
}

/// One agentless passive clause found in a token vector, as a token-index
/// range from the be-verb (`start`) through its past participle (`end`,
/// inclusive).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentlessClauseMatch {
    pub start: usize,
    pub end: usize,
}

/// Scans `tokens` for `be-verb` + `past-participle` pairs with no `by
/// <agent>` phrase within [`AGENT_LOOKAHEAD`] tokens after the participle —
/// architecture §3.5's "passive constructions and agentless clauses" for
/// FR-5.3. A pair immediately followed by a `by` phrase names its actor and
/// is not returned; scanning resumes just past the pair either way, so
/// overlapping matches are never produced.
///
/// A pair tagged with a [`PRO_DROP_LANGUAGES`] language is never treated as a
/// match at all (PRD §8.2a): this heuristic is English-derived and has no
/// way to tell a genuine agentless clause from a pro-drop language's
/// ordinary, grammatical dropped subject, so it stays off for those
/// languages entirely rather than misfire on well-formed sentences.
pub fn find_agentless_clauses(tokens: &[TaggedToken]) -> Vec<AgentlessClauseMatch> {
    let mut matches = Vec::new();
    let mut index = 0;

    while index + 1 < tokens.len() {
        let is_passive_pair = is_be_form(&tokens[index].text)
            && is_past_participle(&tokens[index + 1].text)
            && !is_pro_drop_language(&tokens[index].lang)
            && !is_pro_drop_language(&tokens[index + 1].lang);

        if !is_passive_pair {
            index += 1;
            continue;
        }

        let end = index + 1;
        let has_named_agent = tokens[end + 1..]
            .iter()
            .take(AGENT_LOOKAHEAD)
            .any(|token| token.text.to_lowercase() == "by");

        if !has_named_agent {
            matches.push(AgentlessClauseMatch { start: index, end });
        }

        index = end + 1;
    }

    matches
}

/// The byte range `tokens[start..=end]` would occupy within `tokens`
/// reconstructed as one string, joined by a single ASCII space — the same
/// simplifying assumption `lexicon::evaluation::token_span` makes for a
/// single token, generalised to a multi-token clause. See that function's
/// doc comment for why this is a reconstruction, not a guarantee against
/// the vendor's original spacing.
fn token_range_span(tokens: &[TaggedToken], start: usize, end: usize) -> Range<usize> {
    let prefix: usize = tokens[..start]
        .iter()
        .map(|token| token.text.len() + 1)
        .sum();
    let span_len: usize = tokens[start..=end]
        .iter()
        .map(|token| token.text.len() + 1)
        .sum::<usize>()
        - 1;
    prefix..(prefix + span_len)
}

/// Finds every agentless passive clause in `tokens` (FR-5.3) and gates each
/// one's span confidence (NFR-5.6), producing the same uniform
/// [`TriggerEvent`] shape the lexicon triggers use — an unnamed-actor
/// candidate is suppressed rather than dropped when its own words were
/// misheard, exactly like any other trigger kind this crate emits.
pub fn gate_agentless_clauses(
    utterance_id: impl Into<UtteranceId>,
    tokens: &[TaggedToken],
    min_span_confidence: f32,
) -> Vec<TriggerEvent> {
    let utterance_id = utterance_id.into();

    find_agentless_clauses(tokens)
        .into_iter()
        .map(|clause| {
            let span = token_range_span(tokens, clause.start, clause.end);
            let confidences: Vec<f32> = tokens[clause.start..=clause.end]
                .iter()
                .map(|token| token.confidence)
                .collect();
            gate_span_confidence(
                utterance_id.clone(),
                span,
                &confidences,
                min_span_confidence,
            )
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parse::event::TriggerKind;

    fn token(text: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: "en".to_string(),
            lang_confidence: 0.9,
        }
    }

    fn tokens(words: &[&str]) -> Vec<TaggedToken> {
        words.iter().map(|w| token(w)).collect()
    }

    fn token_lang(text: &str, lang: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    fn tokens_lang(words: &[&str], lang: &str) -> Vec<TaggedToken> {
        words.iter().map(|w| token_lang(w, lang)).collect()
    }

    #[test]
    fn a_passive_clause_with_no_agent_is_found() {
        let words = tokens(&["the", "report", "was", "reviewed"]);

        let matches = find_agentless_clauses(&words);

        assert_eq!(matches, vec![AgentlessClauseMatch { start: 2, end: 3 }]);
    }

    #[test]
    fn a_passive_clause_naming_its_agent_is_not_a_match() {
        let words = tokens(&["the", "report", "was", "reviewed", "by", "the", "team"]);

        assert!(find_agentless_clauses(&words).is_empty());
    }

    #[test]
    fn active_voice_is_not_a_match() {
        let words = tokens(&["the", "team", "reviewed", "the", "report"]);

        assert!(find_agentless_clauses(&words).is_empty());
    }

    #[test]
    fn an_irregular_past_participle_is_recognised() {
        let words = tokens(&["the", "decision", "was", "made"]);

        let matches = find_agentless_clauses(&words);

        assert_eq!(matches, vec![AgentlessClauseMatch { start: 2, end: 3 }]);
    }

    #[test]
    fn a_be_verb_followed_by_a_non_participle_is_not_a_match() {
        let words = tokens(&["the", "report", "was", "great"]);

        assert!(find_agentless_clauses(&words).is_empty());
    }

    #[test]
    fn matching_is_case_insensitive() {
        let words = tokens(&["The", "Report", "WAS", "Reviewed"]);

        let matches = find_agentless_clauses(&words);

        assert_eq!(matches, vec![AgentlessClauseMatch { start: 2, end: 3 }]);
    }

    #[test]
    fn a_by_phrase_outside_the_lookahead_window_does_not_clear_the_clause() {
        let words = tokens(&[
            "the",
            "report",
            "was",
            "reviewed",
            "yesterday",
            "afternoon",
            "sometime",
            "by",
        ]);

        // "by" sits 4 tokens past the participle, outside AGENT_LOOKAHEAD's
        // 3-token window, so this clause still names no actor.
        let matches = find_agentless_clauses(&words);

        assert_eq!(matches, vec![AgentlessClauseMatch { start: 2, end: 3 }]);
    }

    #[test]
    fn two_agentless_clauses_in_one_utterance_are_both_found() {
        let words = tokens(&[
            "the", "report", "was", "reviewed", "and", "the", "budget", "was", "approved",
        ]);

        let matches = find_agentless_clauses(&words);

        assert_eq!(
            matches,
            vec![
                AgentlessClauseMatch { start: 2, end: 3 },
                AgentlessClauseMatch { start: 7, end: 8 },
            ]
        );
    }

    #[test]
    fn empty_tokens_produce_no_matches() {
        assert!(find_agentless_clauses(&[]).is_empty());
    }

    #[test]
    fn a_pro_drop_tagged_clause_is_not_a_match() {
        // Same surface pattern as `a_passive_clause_with_no_agent_is_found`,
        // but tagged as a pro-drop language (PRD §8.2a): the same tokens
        // that would fire for English must not fire here.
        let words = tokens_lang(&["the", "report", "was", "reviewed"], "zh");

        assert!(find_agentless_clauses(&words).is_empty());
    }

    #[test]
    fn japanese_and_korean_are_also_pro_drop_languages() {
        for lang in ["ja", "ko"] {
            let words = tokens_lang(&["the", "report", "was", "reviewed"], lang);

            assert!(
                find_agentless_clauses(&words).is_empty(),
                "expected no match for pro-drop language {lang}"
            );
        }
    }

    #[test]
    fn a_pro_drop_language_regional_variant_is_still_recognised() {
        // "zh-Hans" collapses to "zh" the same way `group_by_language`
        // groups a BCP-47 region/script subtag onto its primary subtag.
        let words = tokens_lang(&["the", "report", "was", "reviewed"], "zh-Hans");

        assert!(find_agentless_clauses(&words).is_empty());
    }

    #[test]
    fn a_code_switched_utterance_only_disables_the_pro_drop_tagged_half() {
        // The be-verb/participle pair itself is tagged "zh"; a separate,
        // English-tagged pair elsewhere in the same utterance still fires.
        let mut words = tokens_lang(&["the", "budget", "was", "approved"], "zh");
        words.extend(tokens_lang(&["the", "report", "was", "reviewed"], "en"));

        let matches = find_agentless_clauses(&words);

        assert_eq!(matches, vec![AgentlessClauseMatch { start: 6, end: 7 }]);
    }

    #[test]
    fn gate_agentless_clauses_emits_nothing_for_a_pro_drop_tagged_utterance() {
        let words = tokens_lang(&["the", "report", "was", "reviewed"], "zh");

        assert!(gate_agentless_clauses("utt-1", &words, 0.6).is_empty());
    }

    #[test]
    fn gate_agentless_clauses_emits_a_fired_event_with_its_span() {
        let words = tokens(&["the", "report", "was", "reviewed"]);

        let events = gate_agentless_clauses("utt-1", &words, 0.6);

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, TriggerKind::Fired);
        assert_eq!(events[0].utterance_id, "utt-1");
        // "the report was reviewed": "the"(0..3) "report"(4..10) "was"(11..14)
        // "reviewed"(15..23).
        assert_eq!(events[0].span, Some(11..23));
    }

    #[test]
    fn gate_agentless_clauses_suppresses_a_low_confidence_span() {
        let mut words = tokens(&["the", "report", "was", "reviewed"]);
        words[3].confidence = 0.2;

        let events = gate_agentless_clauses("utt-1", &words, 0.6);

        assert_eq!(events.len(), 1);
        assert!(matches!(events[0].kind, TriggerKind::Suppressed(_)));
    }

    #[test]
    fn gate_agentless_clauses_emits_nothing_for_an_active_voice_utterance() {
        let words = tokens(&["the", "team", "reviewed", "the", "report"]);

        assert!(gate_agentless_clauses("utt-1", &words, 0.6).is_empty());
    }
}
