//! The `TranscriptionBackend` trait (architecture §3.2) — the seam a
//! streaming ASR vendor plugs into so it can be swapped without the trigger
//! gate, session state, or any other downstream consumer noticing.

use super::event::{Keyterm, StreamId, TranscriptionEvent};

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
    /// Opens the vendor connection for `stream_id` and sends the
    /// engagement's vocabulary as keyterm prompting on that handshake,
    /// before any audio frame is pushed (architecture §3.2, PRD FR-2.9) —
    /// the same vocabulary the record path sends via
    /// `GetEngagementVocabulary` in `app/modules/asr-record`, injected here
    /// on the live path instead. Must be called exactly once per
    /// `stream_id`, before that stream's first `send_audio` call;
    /// implementations must reject a `send_audio` call for a stream that
    /// hasn't been started rather than silently accepting audio without
    /// keyterm context.
    fn start_stream(
        &mut self,
        stream_id: &StreamId,
        keyterms: &[Keyterm],
    ) -> Result<(), BackendError>;

    /// Pushes one frame of 16kHz mono linear PCM16 — the shape
    /// `capture::ring::NormalizingPipeline` guarantees every input path
    /// produces — into the stream identified by `stream_id`.
    ///
    /// Must fail with a [`BackendError`] if `stream_id` hasn't already been
    /// opened via [`TranscriptionBackend::start_stream`] — the keyterm
    /// handshake happening before the first frame (PRD FR-2.9) is an
    /// invariant every implementation enforces, not just documents.
    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError>;

    /// Drains whatever events have arrived since the last call, in arrival
    /// order. Every implementation must translate its own wire format into
    /// [`TranscriptionEvent`] here — that translation is the whole point of
    /// the trait, since this is the last place vendor-specific shape is
    /// allowed to exist.
    fn poll_events(&mut self) -> Vec<TranscriptionEvent>;

    /// Sends one keepalive frame on the vendor connection, independent of
    /// any `stream_id` — the connection this holds open is opened once per
    /// engagement (architecture §14.2), not per stream, so a keepalive has
    /// no stream to address.
    ///
    /// What a "keepalive frame" actually is on the wire (a websocket ping, a
    /// vendor-specific JSON control message, ...) is vendor-defined, which
    /// is why this exists as a trait method rather than something a wrapper
    /// could synthesize generically: only the vendor implementation behind
    /// this method knows the shape that keeps *its* connection from timing
    /// out. [`super::keepalive::KeepaliveBackend`] is the vendor-agnostic
    /// half — it decides *when* to call this on a fixed interval so every
    /// implementation gets that scheduling for free.
    ///
    /// Defaulted to a no-op rather than required: a scripted or
    /// non-networked implementation (this crate's own fakes, or a test
    /// fixture elsewhere) has no real connection to hold open and no reason
    /// to fail here, so it shouldn't be forced to implement a method it has
    /// nothing to do. A real vendor backend overrides this to actually send
    /// its wire-level keepalive.
    fn send_keepalive(&mut self) -> Result<(), BackendError> {
        Ok(())
    }
}
