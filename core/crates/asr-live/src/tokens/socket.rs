use super::event::TokenEvent;
use super::ParticipantId;

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
}
