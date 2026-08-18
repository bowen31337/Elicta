//! In-memory-only retention for captured audio segments (PRD FR-1.7).
//!
//! Audio never reaches persistent storage on the device: normalised samples
//! (`ring::NormalizedFrame`) are handed to a [`SegmentStore`], which returns
//! an opaque [`AudioSegmentRef`] for callers to carry instead of the bytes
//! themselves. The record path borrows samples back out by that ref for
//! transcription and diarization (architecture §7 steps 1/3), and the
//! segment is discarded — its memory freed, nothing ever serialized to disk
//! — the moment the last of those steps finishes (NFR-2.4, ADR-008).
//!
//! Nothing in this module imports `std::fs` or any other persistence API;
//! that absence is the guarantee FR-1.7 asks for, not an implementation
//! detail to double-check elsewhere.

mod segment;
mod store;

pub use segment::{AudioSegmentId, AudioSegmentRef};
pub use store::SegmentStore;
