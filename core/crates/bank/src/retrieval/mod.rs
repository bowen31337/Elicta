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

pub mod cosine;

pub use cosine::{retrieve_ranked_candidates, CandidateVector, RankedCandidate};
