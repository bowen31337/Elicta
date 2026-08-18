//! Model-free instantiation of the winning candidate's question text (ADR-003;
//! architecture §3.6/§3.7).
//!
//! The question bank stores `phrasing` with `{slot}` placeholders --
//! `"What's the slowest {term} the {function} team would still accept?"` --
//! rather than a finished sentence, so the hot path never calls a model to
//! produce the text an operator sees. Architecture §3.6 names the module's
//! whole reason for existing: "A candidate stored as `"What's the slowest
//! {term} the {function} team would still accept?"` is instantiated with
//! the client's actual word from `TriggerEvent.span` and the attendee
//! roster. String interpolation, not inference." [`instantiate`] is that
//! interpolation for the `TriggerEvent.span` half of that sentence: it
//! slices the client's own wording out of the utterance at the trigger's
//! byte range and fills the `{term}` placeholder with it verbatim, never a
//! paraphrase.
//!
//! The other half -- filling a placeholder like `{function}` from the
//! attendee roster -- is a separate value source this module does not
//! implement; [`instantiate`] returns [`PhrasingError::UnresolvedSlot`] for
//! any placeholder that isn't [`SPAN_SLOT`] rather than guessing at it,
//! so a candidate needing roster context fails loudly instead of rendering
//! a half-filled question.
//!
//! `{slot}` parsing (`{{`/`}}` escapes, named-only placeholders) mirrors the
//! compile-time check `apps/service`'s `compiler/tagging/tag_candidates.py`
//! already runs with Python's `string.Formatter` before a candidate is ever
//! persisted -- by the time a phrasing string reaches this module its
//! braces are already known-balanced and every placeholder already named,
//! so [`slots::format_named`] re-validates defensively rather than
//! trusting an upstream guarantee it has no way to see across the
//! service/runtime boundary.
//!
//! [`instantiate`] is only ever reachable for a candidate that already has
//! pre-written phrasing. Architecture §3.7 names the other branch: "falls
//! back to a small-model rewrite only when the slow lane has injected a
//! novel candidate lacking pre-written phrasing." [`fallback`] is that
//! branch, and [`dispatch::render`] is the one entry point that picks
//! between the two the way §3.7 describes, so the branch is decided in one
//! place rather than at every call site that hands phrasing a winner.

mod dispatch;
mod error;
mod fallback;
mod instantiate;
mod slots;

pub use dispatch::{render, WinningCandidate};
pub use error::PhrasingError;
pub use fallback::{
    rewrite_fallback, RewriteError, Rewriter, SlowLaneCandidate, MAX_REWRITE_WORDS,
};
pub use instantiate::{instantiate, Candidate, SPAN_SLOT};
