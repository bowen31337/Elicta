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
//! See `HANDOFF.md` in this directory for the one-line wiring this module
//! still needs from the crate scaffold.

mod event;
mod fake;
mod first_partial_delay;
mod reevaluate;

pub use event::StreamEvent;
pub use fake::PrematureEndpointFakeBackend;
pub use first_partial_delay::{
    FirstPartialDelay, FirstPartialDelayOutOfRange, FIRST_PARTIAL_DELAY, MAX_FIRST_PARTIAL_DELAY,
    MIN_FIRST_PARTIAL_DELAY,
};
pub use reevaluate::{UtteranceReevaluator, DEFAULT_CONTINUATION_WINDOW};
