//! Span-confidence suppression (PRD NFR-5.6, architecture §3.5): the check
//! that keeps a misheard trigger span from ever becoming a nudge.
//!
//! `lexicon` decides *what* matched; this module decides whether the match
//! is trustworthy enough to act on. The two are independent gates on the
//! same candidate span — a term match with no confidence check would let
//! `quantify "fast"` fire when the client actually said "vast" (the M2
//! event NFR-5.6 rationale calls out by name), and a confidence check with
//! no term match has nothing to gate in the first place.

pub mod event;
pub mod gate;

pub use event::{SuppressionReason, TriggerEvent, TriggerKind, UtteranceId};
pub use gate::gate_span_confidence;
