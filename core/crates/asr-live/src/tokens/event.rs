use super::ParticipantId;

/// One token emitted by the ASR vendor for a single participant's stream.
///
/// Every event is tagged with the participant it came from so a downstream
/// consumer merging several participants' streams back together (e.g. for
/// a combined meeting transcript) can always tell which of the N websocket
/// connections produced it, even though each connection only ever carries
/// one participant's audio and never needs to disambiguate itself.
///
/// `confidence` is populated on every token, partial or final alike (PRD
/// FR-2.3, NFR-5.6): it is what the input-span gate reads to decide whether
/// a span is trustworthy enough to act on, and a gate can't evaluate a span
/// that arrived without a score. There is no constructor path that omits
/// it — `partial` and `finalized` both require a caller to supply one
/// rather than defaulting it, since a silently-defaulted confidence would
/// let an ungated span through unnoticed.
#[derive(Debug, Clone, PartialEq)]
pub struct TokenEvent {
    pub participant_id: ParticipantId,
    pub text: String,
    pub is_final: bool,
    pub confidence: f32,
}

impl TokenEvent {
    pub fn partial(
        participant_id: impl Into<ParticipantId>,
        text: impl Into<String>,
        confidence: f32,
    ) -> Self {
        Self {
            participant_id: participant_id.into(),
            text: text.into(),
            is_final: false,
            confidence,
        }
    }

    pub fn finalized(
        participant_id: impl Into<ParticipantId>,
        text: impl Into<String>,
        confidence: f32,
    ) -> Self {
        Self {
            participant_id: participant_id.into(),
            text: text.into(),
            is_final: true,
            confidence,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn partial_and_finalized_tokens_both_carry_the_supplied_confidence() {
        let partial = TokenEvent::partial("alice", "hello", 0.42);
        let finalized = TokenEvent::finalized("alice", "hello", 0.97);

        assert_eq!(partial.confidence, 0.42);
        assert_eq!(finalized.confidence, 0.97);
    }
}
