//! The `TranscriptionBackend` trait (architecture §3.2) — the seam a
//! streaming ASR vendor plugs into so it can be swapped without the trigger
//! gate, session state, or any other downstream consumer noticing.

use super::event::{StreamId, TranscriptionEvent};

/// A backend-level failure: a connection drop, an authentication rejection,
/// a malformed vendor frame the backend can't translate, and so on. Carries
/// the vendor's message rather than dropping it, since a swapped-in
/// vendor's failures still need to be diagnosable at the call site.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackendError(pub String);

/// One live streaming ASR connection for one capture session. Implemented
/// once per vendor (Deepgram Nova-3, AssemblyAI streaming, ... —
/// architecture §3.2); the trigger gate and everything else downstream is
/// written against this trait, never against a concrete vendor type, so a
/// vendor swap is a change to whichever call site constructs the backend
/// and nothing else.
///
/// Deliberately synchronous push/drain rather than `async`: it mirrors the
/// shape `capture::ring::NormalizingPipeline` already uses on the audio
/// side, and it keeps a vendor's actual transport (persistent websocket,
/// chunked HTTP, ...) an implementation detail behind `poll_events` rather
/// than something this trait has an opinion about.
pub trait TranscriptionBackend {
    /// Pushes one frame of 16kHz mono linear PCM16 — the shape
    /// `capture::ring::NormalizingPipeline` guarantees every input path
    /// produces — into the stream identified by `stream_id`.
    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError>;

    /// Drains whatever events have arrived since the last call, in arrival
    /// order. Every implementation must translate its own wire format into
    /// [`TranscriptionEvent`] here — that translation is the whole point of
    /// the trait, since this is the last place vendor-specific shape is
    /// allowed to exist.
    fn poll_events(&mut self) -> Vec<TranscriptionEvent>;
}
