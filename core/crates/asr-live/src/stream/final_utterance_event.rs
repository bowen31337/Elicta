//! The FR-2.3 outbound shape: "System emits a FinalUtterance event on
//! endpoint carrying id, stream_id, speaker tag, start_ms, end_ms, and a
//! token vector." [`backend::FinalUtterance`] already carries every one of
//! those fields (`backend/event.rs`, architecture §3.2) plus two more —
//! `text` and `audio_ref` — that are this crate's own internal bookkeeping
//! rather than part of what FR-2.3 names. This module is the boundary:
//! [`FinalUtteranceEvent`] holds exactly the fields FR-2.3 lists, with
//! `start`/`end` converted from this crate's internal `Duration` into the
//! `start_ms`/`end_ms` millisecond integers FR-2.3 names, and [`on_endpoint`]
//! is what turns a [`StreamEvent`] into one whenever it actually represents
//! an endpoint having fired.

use crate::backend::{FinalUtterance, SpeakerTag, StreamId, Token, UtteranceId};

use super::event::StreamEvent;

/// The event this crate emits on endpoint (PRD FR-2.3): `id`, `stream_id`,
/// `speaker`, `start_ms`, `end_ms`, and `tokens` — no more. `FinalUtterance`'s
/// `text` and `audio_ref` are deliberately left out: `text` is redundant
/// with `tokens` for a consumer that reads spans off the token vector, and
/// `audio_ref` is retained-audio bookkeeping (PRD NFR-2.4) that FR-2.3 never
/// asked to cross this boundary.
#[derive(Debug, Clone, PartialEq)]
pub struct FinalUtteranceEvent {
    pub id: UtteranceId,
    pub stream_id: StreamId,
    pub speaker: SpeakerTag,
    pub start_ms: u64,
    pub end_ms: u64,
    pub tokens: Vec<Token>,
}

impl From<&FinalUtterance> for FinalUtteranceEvent {
    fn from(utterance: &FinalUtterance) -> Self {
        Self {
            id: utterance.id.clone(),
            stream_id: utterance.stream_id.clone(),
            speaker: utterance.speaker.clone(),
            start_ms: utterance.start.as_millis() as u64,
            end_ms: utterance.end.as_millis() as u64,
            tokens: utterance.tokens.clone(),
        }
    }
}

/// Extracts the FR-2.3 event from a [`StreamEvent`], if that event actually
/// represents an endpoint. `Interim` never does. `Final` and `Correction`
/// both do: a `Correction` is continuation re-evaluation (`reevaluate.rs`)
/// replacing an earlier `Final` with the merged, corrected utterance, but it
/// is still an utterance that just closed on endpoint, carrying the same
/// FR-2.3 fields as a `Final` would. A caller reacting to `StreamEvent`
/// should call this once per event rather than special-casing `Final` and
/// `Correction` separately at every call site.
pub fn on_endpoint(event: &StreamEvent) -> Option<FinalUtteranceEvent> {
    match event {
        StreamEvent::Interim(_) => None,
        StreamEvent::Final(utterance) => Some(utterance.into()),
        StreamEvent::Correction { utterance, .. } => Some(utterance.into()),
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::backend::{AudioSegmentRef, InterimHypothesis, UtteranceId};

    fn token(text: &str) -> Token {
        Token { text: text.to_string(), confidence: 0.9, lang: "en".to_string(), lang_confidence: 0.99 }
    }

    fn final_utterance(id: &str) -> FinalUtterance {
        FinalUtterance {
            id: id.to_string(),
            stream_id: "stream-1".to_string(),
            speaker: SpeakerTag::Participant("client-1".to_string()),
            text: "we need to figure out the budget".to_string(),
            start: Duration::from_millis(0),
            end: Duration::from_millis(1800),
            tokens: vec![token("we"), token("need"), token("to")],
            audio_ref: AudioSegmentRef { storage_key: format!("seg-{id}") },
        }
    }

    #[test]
    fn a_final_utterance_carries_exactly_the_fr_2_3_fields_on_endpoint() {
        let utterance = final_utterance("utt-0");
        let event = on_endpoint(&StreamEvent::Final(utterance.clone()))
            .expect("a Final represents an endpoint");

        assert_eq!(event.id, utterance.id);
        assert_eq!(event.stream_id, utterance.stream_id);
        assert_eq!(event.speaker, utterance.speaker);
        assert_eq!(event.start_ms, 0);
        assert_eq!(event.end_ms, 1800);
        assert_eq!(event.tokens, utterance.tokens);
    }

    #[test]
    fn a_correction_is_also_an_endpoint_carrying_the_merged_utterances_fields() {
        let merged = final_utterance("utt-1");
        let event = on_endpoint(&StreamEvent::Correction {
            supersedes: "utt-0".to_string(),
            utterance: merged.clone(),
        })
        .expect("a Correction still represents an utterance closing on endpoint");

        assert_eq!(event.id, merged.id);
        assert_eq!(event.start_ms, 0);
        assert_eq!(event.end_ms, 1800);
        assert_eq!(event.tokens, merged.tokens);
    }

    #[test]
    fn an_interim_never_represents_an_endpoint() {
        let interim = InterimHypothesis {
            stream_id: "stream-1".to_string(),
            text: "we need".to_string(),
            started_at: Duration::from_millis(0),
        };

        assert_eq!(on_endpoint(&StreamEvent::Interim(interim)), None);
    }

    #[test]
    fn millisecond_conversion_matches_the_source_durations_exactly() {
        let mut utterance = final_utterance("utt-2");
        utterance.start = Duration::from_millis(12_345);
        utterance.end = Duration::from_millis(67_890);

        let event = on_endpoint(&StreamEvent::Final(utterance)).expect("a Final represents an endpoint");

        assert_eq!(event.start_ms, 12_345);
        assert_eq!(event.end_ms, 67_890);
    }

    #[test]
    fn the_internal_only_fields_never_leak_into_the_fr_2_3_event() {
        // FinalUtteranceEvent's field set is the compile-time proof: it has
        // no `text` or `audio_ref` field for `text`/`audio_ref` to leak
        // into. This test exists to name that guarantee explicitly rather
        // than leaving it implicit in the struct definition above.
        let utterance = final_utterance("utt-3");
        let event: FinalUtteranceEvent = (&utterance).into();

        assert_eq!(event.id, utterance.id);
        let _: UtteranceId = event.id;
    }
}
