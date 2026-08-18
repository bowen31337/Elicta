use super::event::TokenEvent;
use super::ParticipantId;

/// Where a vendor anchors its confidence scoring: per word/subword token,
/// or only once for a whole utterance.
///
/// The input-span gate reads confidence per span (PRD FR-2.3, NFR-5.6) — an
/// utterance-level scalar can't back that, since it can't tell the gate
/// which specific word within the utterance is untrustworthy. A vendor that
/// only ever produces [`ConfidenceGranularity::UtteranceLevel`] therefore
/// cannot supply this crate's `TokenSocket` boundary, no matter how it's
/// wired up, and [`validate_backend`] exists to catch that at startup
/// rather than let it surface later as silently-wrong gating decisions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConfidenceGranularity {
    PerToken,
    UtteranceLevel,
}

/// A vendor was rejected during startup validation because it can't meet
/// this crate's confidence-granularity requirement (PRD FR-2.3, NFR-5.6).
/// Carries a message describing exactly why, so a caller failing startup
/// on this error can surface something actionable rather than a bare enum
/// variant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendRejected(pub String);

/// Checks a [`TokenSocketFactory`] against this crate's hard requirement —
/// per-token confidence — before any socket is opened against it, so an
/// ASR vendor that only reports one confidence score per whole utterance
/// is rejected at startup with a clear reason instead of being discovered
/// later, once ungated spans have already reached a downstream consumer.
pub fn validate_backend<F: TokenSocketFactory>(factory: &F) -> Result<(), BackendRejected> {
    match factory.confidence_granularity() {
        ConfidenceGranularity::PerToken => Ok(()),
        ConfidenceGranularity::UtteranceLevel => Err(BackendRejected(format!(
            "ASR backend rejected: it reports only utterance-level confidence, but the input-span \
             gate requires per-token confidence (PRD FR-2.3, NFR-5.6) — {} cannot back this crate's \
             TokenSocket boundary",
            std::any::type_name::<F>()
        ))),
    }
}

/// A live websocket connection to the ASR vendor carrying exactly one
/// participant's already-separated audio stream. Kept as a trait — rather
/// than this module reaching for a concrete websocket client — so the
/// per-participant dispatch and lifecycle bookkeeping in
/// [`super::ParticipantTokenStreams`] can be tested without a real socket,
/// and so this crate's actual transport can be swapped without touching
/// that bookkeeping.
pub trait TokenSocket {
    /// Pushes one frame of this participant's audio down the socket and
    /// drains whatever token events the vendor has produced so far. A
    /// socket must never need to know which participant it belongs to —
    /// that identity lives entirely in which socket
    /// [`ParticipantTokenStreams`](super::ParticipantTokenStreams) chose to
    /// route the frame to.
    fn send_audio(&mut self, samples: &[i16]) -> Vec<TokenEvent>;

    /// Ends the vendor session for this participant, e.g. because the
    /// managed capture backend reported that participant left the meeting.
    fn close(&mut self);
}

/// Opens a new dedicated [`TokenSocket`] for a participant. Implementations
/// must open one connection per call and must never hand back a socket
/// already in use by another participant — that invariant, not anything in
/// this trait's signature, is what makes "one websocket per participant
/// stream" (PRD FR-2.10) true, so [`ParticipantTokenStreams`](super::ParticipantTokenStreams)
/// calls `open` at most once per participant and reuses the result for
/// every subsequent frame from that same participant.
pub trait TokenSocketFactory {
    type Socket: TokenSocket;

    fn open(&mut self, participant_id: &ParticipantId) -> Self::Socket;

    /// Declares whether this vendor scores confidence per token or only
    /// once per utterance — checked by [`validate_backend`] before any
    /// socket is opened. Implementations backed by a real per-word-scoring
    /// vendor (the only kind this crate can serve) should return
    /// [`ConfidenceGranularity::PerToken`]; there is no default impl,
    /// since silently defaulting this would let an incapable vendor pass
    /// validation by omission.
    fn confidence_granularity(&self) -> ConfidenceGranularity;
}
