//! Per-participant live token event streams (PRD FR-2.10).
//!
//! Managed capture that separates audio per participant hands this crate
//! one already-isolated audio stream per participant (see
//! `capture::enrol::stream_identity`). This module is what keeps that
//! separation intact all the way through transcription: exactly one
//! websocket connection to the ASR vendor per participant, each producing
//! its own independent, ordered event stream. Multiplexing more than one
//! participant onto a single connection would reintroduce the cross-talk
//! problem managed capture exists to avoid, and is exactly what
//! [`ParticipantTokenStreams`] is built to make structurally impossible.
//!
//! Every finalized token [`ParticipantTokenStreams::dispatch`] produces is
//! also durably recorded to an append-only [`UtteranceTable`] before that
//! same call returns it to its caller — see `utterance_table.rs`.

mod event;
mod registry;
mod socket;
mod utterance_table;

pub use event::TokenEvent;
pub use registry::ParticipantTokenStreams;
pub use socket::{
    validate_backend, BackendRejected, ConfidenceGranularity, TokenSocket, TokenSocketFactory,
};
pub use utterance_table::{FinalizedUtterance, InMemoryUtteranceTable, NotFinal, UtteranceTable};

/// Stable identifier for a meeting participant, as assigned by the managed
/// capture vendor to one of its per-participant streams.
pub type ParticipantId = String;
