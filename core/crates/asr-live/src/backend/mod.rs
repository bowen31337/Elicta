//! Streaming ASR vendor backends (architecture §3.2, PRD FR-2.1-FR-2.3).
//!
//! [`TranscriptionBackend`] is the seam a streaming ASR vendor plugs into:
//! everything downstream — the trigger gate first among them — is written
//! against this trait and the [`TranscriptionEvent`] shape it emits, never
//! against a concrete vendor type, so swapping Deepgram for AssemblyAI (or
//! adding a third vendor) never touches the trigger gate.
//!
//! See `HANDOFF.md` in this directory for the one-line wiring this module
//! still needs from the crate scaffold.

mod encoding;
mod event;
mod fake;
mod framing;
mod region;
mod transcription_backend;

pub use encoding::{AudioEncoding, LINEAR16_16KHZ_MONO};
pub use event::{
    AudioSegmentRef, FinalUtterance, InterimHypothesis, Keyterm, LanguageTag, SpeakerTag,
    StreamId, Token, TranscriptionEvent, UtteranceId,
};
pub use fake::{ImmutablePartialFakeBackend, RevisablePartialFakeBackend};
pub use framing::{AudioFramer, FrameDurationError, FramedBackend, MAX_FRAME_MS, MIN_FRAME_MS};
pub use region::{
    EndpointResolutionError, EngagementId, EngagementRegionRegistry, Region, RegionPinError,
    RegionPinnedBackend, RegionalConnectError, RegionalEndpointResolver, VendorRegionEndpoints,
};
pub use transcription_backend::{BackendError, TranscriptionBackend};
