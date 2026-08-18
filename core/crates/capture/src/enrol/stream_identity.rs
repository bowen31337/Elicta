//! Speaker identity sourced directly from a managed per-participant stream
//! (PRD FR-2.10). Where the capture vendor already hands us one stream per
//! participant, the stream itself is the ground truth for "who said this" —
//! voiceprint verification (see the mixed-stream fallback, PRD FR-1.6) is
//! only needed when that separation isn't available.

use std::fmt;

/// Stable identifier for a meeting participant, as assigned by the managed
/// capture vendor to one of its per-participant streams.
pub type ParticipantId = String;

/// Who an utterance should be attributed to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpeakerIdentity {
    Operator,
    Participant(ParticipantId),
    Unknown,
}

impl fmt::Display for SpeakerIdentity {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SpeakerIdentity::Operator => write!(f, "operator"),
            SpeakerIdentity::Participant(id) => write!(f, "participant:{id}"),
            SpeakerIdentity::Unknown => write!(f, "unknown"),
        }
    }
}

/// How a stream's speaker identity was determined.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IdentitySource {
    /// The stream itself carries the participant identity (managed
    /// per-participant capture, PRD FR-2.10). No verification step runs.
    StreamIdentifier(ParticipantId),
    /// The capture mode delivers a single mixed stream with no
    /// per-participant separation; identity must come from voiceprint
    /// verification instead (PRD FR-1.6).
    RequiresVerification,
}

/// A captured audio stream that may already know which participant it
/// belongs to. Managed per-participant capture backends implement this by
/// returning the identifier the vendor attached to the stream; mixed-stream
/// backends (line-in, loopback, acoustic) return `None`.
pub trait IdentifiedStream {
    /// The participant identifier the managed capture vendor attached to
    /// this stream, if the capture mode separates streams per participant.
    fn stream_participant_id(&self) -> Option<&str>;
}

/// Determines where a stream's speaker identity comes from, preferring the
/// identifier the stream carries over any downstream verification step.
pub fn resolve_identity_source<S: IdentifiedStream + ?Sized>(stream: &S) -> IdentitySource {
    match stream.stream_participant_id() {
        Some(id) => IdentitySource::StreamIdentifier(id.to_string()),
        None => IdentitySource::RequiresVerification,
    }
}

/// Resolves the speaker identity for a stream directly from its stream
/// identifier. Returns `None` when the stream carries no participant
/// identifier, signalling that the caller must fall back to voiceprint
/// verification (PRD FR-1.6) rather than run it unconditionally.
pub fn resolve_speaker_identity<S: IdentifiedStream + ?Sized>(stream: &S) -> Option<SpeakerIdentity> {
    match resolve_identity_source(stream) {
        IdentitySource::StreamIdentifier(id) => Some(SpeakerIdentity::Participant(id)),
        IdentitySource::RequiresVerification => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct ManagedStream {
        participant_id: Option<&'static str>,
    }

    impl IdentifiedStream for ManagedStream {
        fn stream_participant_id(&self) -> Option<&str> {
            self.participant_id
        }
    }

    #[test]
    fn managed_per_participant_stream_yields_identity_directly() {
        let stream = ManagedStream {
            participant_id: Some("participant-42"),
        };

        assert_eq!(
            resolve_identity_source(&stream),
            IdentitySource::StreamIdentifier("participant-42".to_string())
        );
        assert_eq!(
            resolve_speaker_identity(&stream),
            Some(SpeakerIdentity::Participant("participant-42".to_string()))
        );
    }

    #[test]
    fn mixed_stream_requires_verification_fallback() {
        let stream = ManagedStream { participant_id: None };

        assert_eq!(resolve_identity_source(&stream), IdentitySource::RequiresVerification);
        assert_eq!(resolve_speaker_identity(&stream), None);
    }

    #[test]
    fn distinct_participant_ids_resolve_to_distinct_identities() {
        let alice = ManagedStream {
            participant_id: Some("alice"),
        };
        let bob = ManagedStream {
            participant_id: Some("bob"),
        };

        assert_ne!(
            resolve_speaker_identity(&alice),
            resolve_speaker_identity(&bob)
        );
    }
}
