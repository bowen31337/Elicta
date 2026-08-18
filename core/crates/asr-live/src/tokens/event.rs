use super::ParticipantId;

/// One token emitted by the ASR vendor for a single participant's stream.
///
/// Every event is tagged with the participant it came from so a downstream
/// consumer merging several participants' streams back together (e.g. for
/// a combined meeting transcript) can always tell which of the N websocket
/// connections produced it, even though each connection only ever carries
/// one participant's audio and never needs to disambiguate itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenEvent {
    pub participant_id: ParticipantId,
    pub text: String,
    pub is_final: bool,
}

impl TokenEvent {
    pub fn partial(participant_id: impl Into<ParticipantId>, text: impl Into<String>) -> Self {
        Self {
            participant_id: participant_id.into(),
            text: text.into(),
            is_final: false,
        }
    }

    pub fn finalized(participant_id: impl Into<ParticipantId>, text: impl Into<String>) -> Self {
        Self {
            participant_id: participant_id.into(),
            text: text.into(),
            is_final: true,
        }
    }
}
