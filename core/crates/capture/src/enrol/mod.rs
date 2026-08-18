//! Speaker enrolment and attribution.
//!
//! Two ways an utterance gets attributed to a speaker: directly from a
//! managed per-participant stream's identifier ([`stream_identity`], PRD
//! FR-2.10), or, when capture only provides a single mixed stream, by
//! voiceprint verification against the operator's enrolled sample (PRD
//! FR-1.5/FR-1.6). [`enrolment`] produces that enrolled sample in the first
//! place.

mod enrolment;
mod stream_identity;

pub use enrolment::{
    EmptyEnrolmentError, EnrolmentRecorder, OperatorVoiceprint, VoiceEmbedder,
    MAX_ENROLMENT_DURATION_MS,
};
pub use stream_identity::{
    resolve_identity_source, resolve_speaker_identity, IdentifiedStream, IdentitySource,
    ParticipantId, SpeakerIdentity,
};
