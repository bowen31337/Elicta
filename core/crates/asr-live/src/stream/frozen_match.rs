//! The FR-2.4 mechanism named concretely in architecture §14.2 ("Use the
//! frozen-but-not-ended signal"): Deepgram distinguishes `is_final` (these
//! tokens will not be revised) from `speech_final` (the endpoint fired).
//! Matching on `is_final` text that has not yet endpointed buys the entire
//! remaining endpoint wait at zero risk, because the tokens are already
//! immutable — no invalidation logic is needed the way it would be for a
//! match against still-revisable text (architecture §3.2's "prefer engines
//! whose streaming output is immutable").
//!
//! `backend::InterimHypothesis` carries no such bit today — Deepgram's
//! `is_final` has no field on that type yet (see `HANDOFF.md`) — so this
//! module takes it from the caller, the same way `interim_latency.rs` takes
//! `observed_at` rather than reading a clock of its own: whoever is closest
//! to the vendor wire is the one who actually knows whether a given interim
//! was frozen.

use crate::backend::{InterimHypothesis, StreamId};

/// Whether a vendor has frozen an [`InterimHypothesis`]'s text (Deepgram's
/// `is_final`) or it remains subject to revision. Distinct from whether the
/// *utterance* has endpointed (`speech_final`, [`super::FinalUtteranceEvent`]
/// /[`super::on_endpoint`]) — a stream can sit in `Frozen` for one or more
/// interims before the endpoint that closes the utterance ever fires.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenStability {
    /// The vendor may still rewrite this text in a later interim for the
    /// same utterance. Matching against it is exactly the invalidation-prone
    /// case immutable partials (FR-2.4) exist to avoid.
    Revisable,
    /// The vendor guarantees this text will not be revised, independent of
    /// whether the utterance itself has endpointed yet.
    Frozen,
}

/// An [`InterimHypothesis`] paired with whether the vendor has frozen its
/// text. The stability bit is supplied by the caller (see module docs) —
/// this type only carries it, it does not infer it.
#[derive(Debug, Clone, PartialEq)]
pub struct StableInterim {
    pub interim: InterimHypothesis,
    pub stability: TokenStability,
}

/// A speculative match committed against frozen (immutable) text, ahead of
/// the endpoint that would otherwise be required before trusting it (PRD
/// FR-2.4). Because the matched span came from tokens the vendor guarantees
/// will not be revised, this candidate needs no discard/invalidation path
/// if the endpoint later closes the utterance differently — the span it was
/// matched against can never change underneath it.
#[derive(Debug, Clone, PartialEq)]
pub struct CommittedCandidate<M> {
    pub stream_id: StreamId,
    pub matched_text: String,
    pub matched: M,
}

/// Runs `matcher` against `stable`'s text only when its tokens are frozen,
/// producing a [`CommittedCandidate`] immediately on a match rather than
/// waiting for that stream's endpoint to fire. A match against
/// [`TokenStability::Revisable`] text never reaches `matcher`: committing
/// on text the vendor might still rewrite is precisely what immutable
/// partials (FR-2.4) let this function avoid, so revisable text is left for
/// the endpoint to confirm instead.
pub fn commit_on_frozen_match<M>(
    stable: &StableInterim,
    matcher: impl FnOnce(&str) -> Option<M>,
) -> Option<CommittedCandidate<M>> {
    if stable.stability != TokenStability::Frozen {
        return None;
    }
    matcher(&stable.interim.text).map(|matched| CommittedCandidate {
        stream_id: stable.interim.stream_id.clone(),
        matched_text: stable.interim.text.clone(),
        matched,
    })
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::backend::{AudioSegmentRef, FinalUtterance, SpeakerTag, Token};
    use crate::stream::{on_endpoint, StreamEvent};

    fn token(text: &str) -> Token {
        Token { text: text.to_string(), confidence: 0.9, lang: "en".to_string(), lang_confidence: 0.99 }
    }

    fn stable(text: &str, stability: TokenStability) -> StableInterim {
        StableInterim {
            interim: InterimHypothesis {
                stream_id: "stream-1".to_string(),
                text: text.to_string(),
                started_at: Duration::from_millis(0),
            },
            stability,
        }
    }

    fn keyterm_matcher(term: &'static str) -> impl FnOnce(&str) -> Option<String> {
        move |text: &str| text.contains(term).then(|| term.to_string())
    }

    #[test]
    fn a_frozen_match_commits_a_candidate() {
        let interim = stable("we need to figure out the budget", TokenStability::Frozen);

        let committed = commit_on_frozen_match(&interim, keyterm_matcher("budget"))
            .expect("frozen text matching the keyterm should commit");

        assert_eq!(committed.stream_id, "stream-1");
        assert_eq!(committed.matched_text, "we need to figure out the budget");
        assert_eq!(committed.matched, "budget");
    }

    #[test]
    fn a_revisable_match_never_commits() {
        let interim = stable("we need to figure out the budget", TokenStability::Revisable);

        let committed = commit_on_frozen_match(&interim, keyterm_matcher("budget"));

        assert_eq!(committed, None, "text the vendor might still rewrite must not commit early");
    }

    #[test]
    fn a_frozen_hypothesis_with_no_match_commits_nothing() {
        let interim = stable("we need to figure out the timeline", TokenStability::Frozen);

        let committed = commit_on_frozen_match(&interim, keyterm_matcher("budget"));

        assert_eq!(committed, None);
    }

    #[test]
    fn a_frozen_match_commits_before_the_streams_endpoint_ever_fires() {
        // The scenario FR-2.4 exists for: a frozen interim carrying the
        // matched text arrives, and only afterwards does the same stream's
        // Final close the utterance on endpoint. The committed candidate
        // must already exist at the frozen-interim step, strictly before
        // `on_endpoint` has anything to say about this stream at all.
        let frozen = stable("we need to figure out the budget", TokenStability::Frozen);

        let committed = commit_on_frozen_match(&frozen, keyterm_matcher("budget"))
            .expect("frozen match commits immediately, without waiting on the endpoint");

        // The endpoint for this same utterance has not fired yet at the
        // point the candidate was committed above.
        let interim_event = StreamEvent::Interim(frozen.interim.clone());
        assert_eq!(on_endpoint(&interim_event), None, "no endpoint has fired yet");

        // Only later does the utterance actually close.
        let endpoint = FinalUtterance {
            id: "utt-0".to_string(),
            stream_id: "stream-1".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            text: "we need to figure out the budget".to_string(),
            start: Duration::from_millis(0),
            end: Duration::from_millis(1800),
            tokens: vec![token("we"), token("need")],
            audio_ref: AudioSegmentRef { storage_key: "seg-0".to_string() },
        };
        let final_event = StreamEvent::Final(endpoint);
        assert!(on_endpoint(&final_event).is_some(), "the endpoint fires only now");

        assert_eq!(committed.matched, "budget");
    }
}
