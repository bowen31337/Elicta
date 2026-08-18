//! Holds a lexicon match found against an interim hypothesis until that
//! stream's endpoint arrives to commit or discard it (PRD FR-5.9).
//!
//! [`router::LexiconRouter::run`] has no notion of "interim" vs "final" — it
//! scans whatever tokens it is handed. An interim hypothesis's tokens are
//! revisable: the vendor may still rewrite the very word a match was found
//! in before the utterance endpoints. That is the opposite case from
//! `asr-live::stream::frozen_match`'s `CommittedCandidate` (PRD FR-2.4),
//! which never needs a discard path because its text is guaranteed
//! immutable by the vendor's own `is_final` bit — a match against
//! *revisable* text carries no such guarantee, so acting on it immediately
//! risks surfacing a nudge for wording the client never actually finished
//! saying. [`CandidateHold`] is the middle ground: hold the match rather
//! than dropping it or acting on it, until the same stream's endpoint
//! supplies the final, immutable token vector to check it against.

use std::collections::HashMap;

use super::grouping::TaggedToken;
use super::router::LexiconRouter;
use super::terms::LexiconMatch;

/// A lexicon match found against an interim hypothesis's tokens, held
/// rather than committed because those tokens may still be revised before
/// the stream's endpoint fires.
#[derive(Debug, Clone, PartialEq)]
pub struct HeldCandidate {
    pub stream_id: String,
    pub interim_match: LexiconMatch,
}

/// What became of a [`HeldCandidate`] once its stream's endpoint arrived.
#[derive(Debug, Clone, PartialEq)]
pub enum Resolution {
    /// The endpoint's final token vector still carries this exact match
    /// (same token index, language, and term) — the interim text held up,
    /// so the candidate may proceed the same as a frozen-text match would.
    Committed(LexiconMatch),
    /// The endpoint's final token vector no longer carries this match — the
    /// vendor revised or dropped the very token the interim match depended
    /// on, so the held candidate is discarded rather than surfaced on text
    /// the client never actually finished saying.
    Discarded {
        held: LexiconMatch,
        reason: DiscardReason,
    },
}

/// Why a [`HeldCandidate`] was discarded rather than committed.
#[derive(Debug, Clone, PartialEq)]
pub enum DiscardReason {
    /// The endpoint fired with no lexicon match at this candidate's own
    /// token index, language, and term — the word was revised away or
    /// reworded past recognition before the utterance closed.
    NoLongerMatched,
}

/// Holds lexicon matches per stream, keyed by `stream_id`, until each
/// stream's endpoint resolves them via [`CandidateHold::resolve_endpoint`].
#[derive(Debug, Default)]
pub struct CandidateHold {
    held: HashMap<String, Vec<HeldCandidate>>,
}

impl CandidateHold {
    pub fn new() -> Self {
        CandidateHold {
            held: HashMap::new(),
        }
    }

    /// Scans `interim_tokens` with `router` and holds every resulting match
    /// under `stream_id`, appending to any candidates already held for that
    /// stream from an earlier interim of the same utterance. Returns only
    /// the candidates newly held by this call, not the stream's full
    /// backlog — nothing here is committed or discarded yet.
    pub fn hold_interim(
        &mut self,
        stream_id: impl Into<String>,
        router: &LexiconRouter,
        interim_tokens: &[TaggedToken],
        min_tag_confidence: f32,
    ) -> Vec<HeldCandidate> {
        let stream_id = stream_id.into();
        let newly_held: Vec<HeldCandidate> = router
            .run(interim_tokens, min_tag_confidence)
            .into_iter()
            .map(|interim_match| HeldCandidate {
                stream_id: stream_id.clone(),
                interim_match,
            })
            .collect();

        self.held
            .entry(stream_id)
            .or_default()
            .extend(newly_held.iter().cloned());

        newly_held
    }

    /// `stream_id`'s endpoint has fired: resolves and drains every candidate
    /// held for that stream, checking each against `final_tokens` — the
    /// endpoint's own, now-immutable token vector — via `router`. Returns
    /// one [`Resolution`] per held candidate, in the order they were
    /// originally held. A stream with nothing held returns an empty vector
    /// rather than an error: not every endpoint follows an interim match.
    ///
    /// After this call, `stream_id` has nothing held — a later endpoint for
    /// the same stream (a fresh utterance) starts from a clean slate rather
    /// than re-resolving already-settled candidates.
    pub fn resolve_endpoint(
        &mut self,
        stream_id: &str,
        router: &LexiconRouter,
        final_tokens: &[TaggedToken],
        min_tag_confidence: f32,
    ) -> Vec<Resolution> {
        let pending = match self.held.remove(stream_id) {
            Some(pending) => pending,
            None => return Vec::new(),
        };

        let final_matches = router.run(final_tokens, min_tag_confidence);

        pending
            .into_iter()
            .map(|candidate| {
                let still_matches = final_matches.iter().any(|m| {
                    m.token_index == candidate.interim_match.token_index
                        && m.language == candidate.interim_match.language
                        && m.term == candidate.interim_match.term
                });

                if still_matches {
                    Resolution::Committed(candidate.interim_match)
                } else {
                    Resolution::Discarded {
                        held: candidate.interim_match,
                        reason: DiscardReason::NoLongerMatched,
                    }
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexicon::terms::Lexicon;

    fn token(text: &str, lang: &str) -> TaggedToken {
        TaggedToken {
            text: text.to_string(),
            confidence: 0.9,
            lang: lang.to_string(),
            lang_confidence: 0.9,
        }
    }

    fn router_with_en_lexicon() -> LexiconRouter {
        let mut router = LexiconRouter::new();
        router.register(Lexicon::new("en", ["several", "a lot"]));
        router
    }

    #[test]
    fn an_interim_match_is_held_rather_than_committed_immediately() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();

        let held = hold.hold_interim("stream-1", &router, &[token("we need several", "en")], 0.6);

        assert_eq!(held.len(), 1);
        assert_eq!(held[0].stream_id, "stream-1");
        assert_eq!(held[0].interim_match.term, "several");
    }

    #[test]
    fn endpoint_confirming_the_same_text_commits_the_held_candidate() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();
        let interim_tokens = [token("we need several", "en")];
        hold.hold_interim("stream-1", &router, &interim_tokens, 0.6);

        let resolutions = hold.resolve_endpoint("stream-1", &router, &interim_tokens, 0.6);

        assert_eq!(resolutions.len(), 1);
        assert!(matches!(
            &resolutions[0],
            Resolution::Committed(m) if m.term == "several"
        ));
    }

    #[test]
    fn endpoint_revising_the_matched_text_away_discards_the_held_candidate() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();
        hold.hold_interim("stream-1", &router, &[token("we need several", "en")], 0.6);

        // The vendor revised the interim into a final that no longer
        // contains the ambiguous term at all.
        let final_tokens = [token("we need three", "en")];
        let resolutions = hold.resolve_endpoint("stream-1", &router, &final_tokens, 0.6);

        assert_eq!(resolutions.len(), 1);
        assert_eq!(
            resolutions[0],
            Resolution::Discarded {
                held: LexiconMatch {
                    token_index: 0,
                    language: "en".to_string(),
                    term: "several".to_string(),
                    matched_text: "we need several".to_string(),
                },
                reason: DiscardReason::NoLongerMatched,
            }
        );
    }

    #[test]
    fn resolving_drains_the_stream_so_a_later_endpoint_starts_clean() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();
        let interim_tokens = [token("several", "en")];
        hold.hold_interim("stream-1", &router, &interim_tokens, 0.6);

        let first = hold.resolve_endpoint("stream-1", &router, &interim_tokens, 0.6);
        assert_eq!(first.len(), 1);

        // Nothing new was held for this stream since the first resolve, so
        // a second endpoint (e.g. a later utterance on the same stream)
        // must not re-resolve the already-settled candidate.
        let second = hold.resolve_endpoint("stream-1", &router, &interim_tokens, 0.6);
        assert!(second.is_empty());
    }

    #[test]
    fn a_stream_with_nothing_held_resolves_to_an_empty_vector() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();

        let resolutions = hold.resolve_endpoint("stream-1", &router, &[token("plain", "en")], 0.6);

        assert!(resolutions.is_empty());
    }

    #[test]
    fn multiple_interims_for_the_same_stream_accumulate_until_one_endpoint_resolves_them_all() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();
        // Each interim's token index is only meaningful relative to that
        // interim's own token vector; here the second interim's "a lot"
        // sits at index 1 to line up with where it ends up in the final
        // token vector below.
        hold.hold_interim("stream-1", &router, &[token("several", "en")], 0.6);
        hold.hold_interim(
            "stream-1",
            &router,
            &[token("we need", "en"), token("a lot", "en")],
            0.6,
        );

        let final_tokens = [token("several", "en"), token("a lot", "en")];
        let resolutions = hold.resolve_endpoint("stream-1", &router, &final_tokens, 0.6);

        assert_eq!(resolutions.len(), 2);
        assert!(resolutions
            .iter()
            .all(|r| matches!(r, Resolution::Committed(_))));
    }

    #[test]
    fn resolving_one_streams_endpoint_does_not_touch_another_streams_held_candidates() {
        let router = router_with_en_lexicon();
        let mut hold = CandidateHold::new();
        hold.hold_interim("stream-1", &router, &[token("several", "en")], 0.6);
        hold.hold_interim("stream-2", &router, &[token("a lot", "en")], 0.6);

        let stream_1_final = [token("several", "en")];
        let resolutions = hold.resolve_endpoint("stream-1", &router, &stream_1_final, 0.6);
        assert_eq!(resolutions.len(), 1);

        // stream-2's candidate is still held, untouched by stream-1's
        // endpoint.
        let stream_2_final = [token("a lot", "en")];
        let stream_2_resolutions = hold.resolve_endpoint("stream-2", &router, &stream_2_final, 0.6);
        assert_eq!(stream_2_resolutions.len(), 1);
        assert!(matches!(
            &stream_2_resolutions[0],
            Resolution::Committed(m) if m.term == "a lot"
        ));
    }
}
