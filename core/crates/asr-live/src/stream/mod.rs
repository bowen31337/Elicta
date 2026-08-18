//! Continuation re-evaluation for the live ASR path (architecture §14.2:
//! "tune endpointing aggressively ... the cost is more premature endpoints
//! mid-sentence, which the trigger gate must tolerate by re-evaluating
//! when a continuation arrives").
//!
//! Sits between [`super::backend::TranscriptionBackend::poll_events`] and
//! whatever consumes its output. Aggressive endpointing tuning buys
//! latency by cutting utterances mid-sentence more often; this module is
//! what keeps that trade from leaking two contradictory, independent
//! utterances to everything downstream when the second is really the
//! first one's continuation.
//!
//! Also holds [`FirstPartialDelay`] (PRD FR-5.9): the companion latency
//! decision that sets how soon the engine emits its *first* partial,
//! rather than how a *finalised* utterance is corrected after the fact.
//!
//! And [`EndpointingThresholds`] (PRD FR-2.2): the silence threshold that
//! drives endpointing itself, exposed as configuration with a 600ms
//! default and tuned independently per [`CaptureMode`] rather than shared
//! across every capture path.
//!
//! And [`TurnSilenceParameters`]/[`TuningReport`] (architecture §14.2, T2):
//! the confidence/punctuation-based engines' `min_turn_silence`/
//! `max_turn_silence` split that `EndpointingThresholds`' single knob
//! under-specifies, plus the tuning run that reports p50 and p95 as
//! independent measurements rather than one blended verdict.
//!
//! And [`check_interim_latency`] (PRD FR-2.1): the check that an
//! `InterimHypothesis` actually reached a consumer within 400ms of the
//! speech onset it carries in `started_at`, not just that the field itself
//! is populated.
//!
//! And [`FinalUtteranceEvent`]/[`on_endpoint`] (PRD FR-2.3): the event this
//! crate actually emits when an endpoint fires, carrying exactly `id`,
//! `stream_id`, `speaker`, `start_ms`, `end_ms`, and `tokens` — converting
//! `FinalUtterance`'s internal `Duration`s into the millisecond integers
//! FR-2.3 names, and leaving `text`/`audio_ref` behind as this crate's own
//! bookkeeping.
//!
//! See `HANDOFF.md` in this directory for the one-line wiring this module
//! still needs from the crate scaffold.

mod endpointing_threshold;
mod event;
mod fake;
mod final_utterance_event;
mod first_partial_delay;
mod interim_latency;
mod reevaluate;
mod turn_silence;

pub use endpointing_threshold::{CaptureMode, EndpointingThresholds, DEFAULT_ENDPOINTING_THRESHOLD};
pub use event::StreamEvent;
pub use final_utterance_event::{on_endpoint, FinalUtteranceEvent};
pub use fake::PrematureEndpointFakeBackend;
pub use first_partial_delay::{
    FirstPartialDelay, FirstPartialDelayOutOfRange, FIRST_PARTIAL_DELAY, MAX_FIRST_PARTIAL_DELAY,
    MIN_FIRST_PARTIAL_DELAY,
};
pub use interim_latency::{check_interim_latency, InterimLatencyExceeded, INTERIM_LATENCY_BUDGET};
pub use reevaluate::{UtteranceReevaluator, DEFAULT_CONTINUATION_WINDOW};
pub use turn_silence::{
    LatencyMeasurement, TuningReport, TurnSilenceParameters, DEFAULT_MAX_TURN_SILENCE,
    DEFAULT_MIN_TURN_SILENCE, P50_LATENCY_TARGET, P95_LATENCY_TARGET, PRO_MAX_TURN_SILENCE,
    PRO_MAX_TURN_SILENCE_WITH_SPEAKER_LABELS, TUNING_STEP,
};
