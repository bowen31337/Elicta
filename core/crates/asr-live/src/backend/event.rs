//! Event and value types every [`super::TranscriptionBackend`] emits
//! (architecture §3.2). These are deliberately the *only* thing a caller —
//! ultimately the trigger gate — ever sees; no vendor-specific wire format
//! is allowed to cross this boundary.

use std::time::Duration;

/// Identifies which captured audio stream an event belongs to. On managed
/// per-participant capture this is the vendor's own stream identifier
/// (architecture §3.3, PRD FR-2.10); on mixed-stream capture it is the one
/// stream shared by every participant.
pub type StreamId = String;

/// Opaque identifier for a [`FinalUtterance`], stable for the lifetime of
/// the session so downstream consumers (citations, coverage) can refer back
/// to a specific utterance.
pub type UtteranceId = String;

/// Who an utterance is attributed to (architecture §3.3). Mirrors the shape
/// of `capture::enrol::SpeakerIdentity`; kept local to this module rather
/// than depending on the `capture` crate directly, since that dependency
/// isn't wired up yet (see `HANDOFF.md` in this directory) and this module
/// is otherwise self-contained.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpeakerTag {
    Operator,
    Participant(String),
    Unknown,
}

/// BCP-47 language tag, assigned per token rather than per utterance
/// (architecture §3.2, PRD FR-2.13) — a code-switched utterance carries more
/// than one language tag across its tokens.
pub type LanguageTag = String;

/// One term from the engagement's vocabulary (client name, product names,
/// internal systems, acronyms) injected as keyterm prompting on the
/// handshake before the first audio frame is sent (architecture §3.2, PRD
/// FR-2.9) — the same vocabulary the record path sends via
/// `GetEngagementVocabulary` in `app/modules/asr-record`, kept as a plain
/// `String` alias here since this crate doesn't depend on that package.
pub type Keyterm = String;

/// One recognised word or subword unit within a [`FinalUtterance`]. Carries
/// per-token confidence and language rather than one scalar per utterance
/// (architecture §3.2): span-confidence suppression (NFR-5.6) and
/// language-tag suppression (FR-2.22) both gate on an individual span, and
/// an utterance-level scalar can't express either. A backend that only
/// emits utterance-level confidence and language fails FR-2.3 and
/// disqualifies itself from the live path — architecture §3.2 calls this
/// out as a hard filter in the vendor bake-off, not something to discover
/// during integration.
#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub text: String,
    pub confidence: f32,
    pub lang: LanguageTag,
    pub lang_confidence: f32,
}

/// Reference to the retained audio segment backing a [`FinalUtterance`].
/// Retained only until the record path completes (PRD NFR-2.4) — this type
/// carries the reference to that segment, not the audio bytes themselves.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioSegmentRef {
    pub storage_key: String,
}

/// A not-yet-finalised partial transcript (architecture §3.2, PRD FR-2.1).
/// Vendors differ on whether a later interim for the same `stream_id`
/// revises an earlier one in place or only ever appends (architecture §3.2,
/// "prefer engines whose streaming output is immutable") — that difference
/// lives in the *sequence* of `InterimHypothesis` values a backend emits,
/// never in this type's shape.
#[derive(Debug, Clone, PartialEq)]
pub struct InterimHypothesis {
    pub stream_id: StreamId,
    pub text: String,
    pub started_at: Duration,
}

/// A finalised utterance on endpoint (architecture §3.2, PRD FR-2.3).
#[derive(Debug, Clone, PartialEq)]
pub struct FinalUtterance {
    pub id: UtteranceId,
    pub stream_id: StreamId,
    pub speaker: SpeakerTag,
    pub text: String,
    pub start: Duration,
    pub end: Duration,
    pub tokens: Vec<Token>,
    pub audio_ref: AudioSegmentRef,
}

/// The one event shape every [`super::TranscriptionBackend`] implementation
/// emits (architecture §3.2). This enum *is* the seam the trait exists to
/// protect: the trigger gate, session state, and every other downstream
/// consumer pattern-match on `TranscriptionEvent`, never on a vendor's wire
/// format, so replacing Deepgram with AssemblyAI — or adding a third vendor
/// — never touches a downstream consumer.
#[derive(Debug, Clone, PartialEq)]
pub enum TranscriptionEvent {
    Interim(InterimHypothesis),
    Final(FinalUtterance),
}
