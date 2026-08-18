//! The event shape this module emits after passing raw backend output
//! through continuation re-evaluation (architecture §14.2: "tune
//! endpointing aggressively ... the cost is more premature endpoints
//! mid-sentence, which the trigger gate must tolerate by re-evaluating
//! when a continuation arrives").
//!
//! Interims pass through unchanged here — only a finalised utterance can
//! turn out to have ended prematurely, since a premature *endpoint* is
//! exactly what this module exists to correct.

use crate::backend::{FinalUtterance, InterimHypothesis, UtteranceId};

/// One event downstream of continuation re-evaluation. A caller who
/// forwards every backend `Final` unmodified to a trigger gate is exactly
/// as correct as the raw backend contract, but it misses the point of this
/// module: [`StreamEvent::Correction`] is the signal that an earlier
/// `Final` the gate may already have reacted to needs retracting, not
/// treating as a second, independent utterance.
#[derive(Debug, Clone, PartialEq)]
pub enum StreamEvent {
    /// Forwarded unchanged from the backend.
    Interim(InterimHypothesis),
    /// A finalised utterance with no earlier utterance on this stream
    /// close enough in time to be its continuation.
    Final(FinalUtterance),
    /// A continuation arrived soon enough after an earlier finalised
    /// utterance that the two are re-evaluated as one: `utterance` is the
    /// merged, corrected result and `supersedes` is the id of the
    /// utterance it replaces. A consumer that already reacted to
    /// `supersedes` must retract that reaction rather than additionally
    /// reacting to this one as if it were independent speech.
    Correction {
        supersedes: UtteranceId,
        utterance: FinalUtterance,
    },
}
