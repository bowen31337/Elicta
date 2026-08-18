//! An audio segment retained in memory for the span of one utterance (PRD
//! FR-1.7). This is the only representation raw audio takes downstream of
//! capture: never a file path, never a byte buffer handed to a filesystem
//! API. A [`RetainedSegment`] owns its samples for as long as transcription
//! and diarization need them (NFR-2.4), and dropping it is the entire
//! discard mechanism (ADR-008).

/// Opaque identifier for a segment held by a [`super::SegmentStore`].
///
/// Assigned by the store itself from a plain counter — never derived from a
/// filesystem path or anything else that would let a path-shaped identifier
/// creep into this module.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct AudioSegmentId(u64);

impl AudioSegmentId {
    pub(super) fn new(value: u64) -> Self {
        Self(value)
    }
}

/// A handle to an in-memory audio segment, carried by a `FinalUtterance`
/// (architecture §3.2) instead of the samples themselves. Consumers exchange
/// this for the underlying samples through [`super::SegmentStore::get`] and
/// signal that a segment is no longer needed through
/// [`super::SegmentStore::discard`]. There is no way to reach the audio
/// through this type alone — ownership of "where the bytes live" stays
/// entirely inside the store.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AudioSegmentRef {
    id: AudioSegmentId,
}

impl AudioSegmentRef {
    pub(super) fn new(id: AudioSegmentId) -> Self {
        Self { id }
    }

    pub fn id(&self) -> AudioSegmentId {
        self.id
    }
}

/// 16kHz mono linear PCM16 samples (the `ring::NormalizedFrame` shape) for
/// one utterance's span, owned by the store until discarded.
pub(super) struct RetainedSegment {
    pub samples: Vec<i16>,
}
