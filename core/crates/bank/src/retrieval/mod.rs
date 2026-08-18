//! Brute-force cosine retrieval over the compiled question bank (PRD FR-4.3,
//! architecture §3.6): "Local SQLite with a vector index (sqlite-vec, or a
//! flat index -- at a few hundred candidates, brute-force cosine is
//! sub-millisecond and an approximate index is unnecessary complexity)."
//!
//! This module is the flat-index half of that sentence: it takes a query
//! embedding and the bank's candidate vectors already loaded into memory --
//! no SQLite, no I/O -- and returns every candidate ranked by cosine
//! similarity, matching architecture §3.7's "pure function, no I/O beyond
//! the local index" contract that the ranking/phrasing stage downstream
//! also follows.
//!
//! [`prerequisite`] is the other half architecture §3.7 requires before
//! that scoring runs: "candidates whose `requires` prerequisites are
//! unsatisfied are filtered before scoring." It's a separate pre-filter
//! stage, not part of [`cosine`]'s scoring itself, so a caller applies it to
//! the candidate list before ever computing a cosine score.

pub mod cosine;
pub mod prerequisite;

pub use cosine::{retrieve_ranked_candidates, CandidateVector, RankedCandidate};
pub use prerequisite::{filter_unsatisfied_prerequisites, PrerequisiteCandidate};
