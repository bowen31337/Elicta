use std::fmt;
use std::ops::Range;

use super::slots::SlotError;

/// Why [`super::instantiate`] could not turn a candidate's stored phrasing
/// into a fully formed question string.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PhrasingError {
    /// `trigger_span` reaches past the end of `utterance_text` (or its
    /// start exceeds its end) -- the gate that produced it and the
    /// utterance handed to instantiation disagree about what was said.
    SpanOutOfBounds {
        span: Range<usize>,
        utterance_len: usize,
    },
    /// `trigger_span` lands mid-codepoint in `utterance_text`, so slicing it
    /// out verbatim would panic rather than yield the client's actual word.
    SpanNotOnCharBoundary { span: Range<usize> },
    /// The candidate's `phrasing` has an unclosed `{`, a bare `}`, or an
    /// anonymous `{}` placeholder that can never be resolved by name.
    MalformedPlaceholder { candidate_id: String },
    /// A named placeholder in `phrasing` other than [`super::SPAN_SLOT`] --
    /// this module only ever resolves the trigger-span slot; a candidate
    /// needing e.g. an attendee-roster value fails here rather than
    /// rendering a half-filled question.
    UnresolvedSlot { candidate_id: String, slot: String },
}

impl PhrasingError {
    pub(super) fn from_slot_error(candidate_id: &str, err: SlotError) -> Self {
        match err {
            SlotError::UnbalancedBrace | SlotError::AnonymousPlaceholder => {
                PhrasingError::MalformedPlaceholder {
                    candidate_id: candidate_id.to_string(),
                }
            }
            SlotError::UnresolvedSlot(slot) => PhrasingError::UnresolvedSlot {
                candidate_id: candidate_id.to_string(),
                slot,
            },
        }
    }
}

impl fmt::Display for PhrasingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PhrasingError::SpanOutOfBounds { span, utterance_len } => write!(
                f,
                "trigger span {span:?} is out of bounds for a {utterance_len}-byte utterance"
            ),
            PhrasingError::SpanNotOnCharBoundary { span } => {
                write!(f, "trigger span {span:?} does not fall on a character boundary")
            }
            PhrasingError::MalformedPlaceholder { candidate_id } => write!(
                f,
                "candidate {candidate_id:?} has a malformed {{slot}} placeholder in its phrasing"
            ),
            PhrasingError::UnresolvedSlot { candidate_id, slot } => write!(
                f,
                "candidate {candidate_id:?} phrasing needs slot {slot:?}, which the trigger span cannot fill"
            ),
        }
    }
}

impl std::error::Error for PhrasingError {}
