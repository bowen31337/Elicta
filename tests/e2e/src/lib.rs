//! End-to-end composition tests spanning `language` and `trigger-gate`.
//!
//! Those two crates are deliberately not linked to each other yet (see
//! `trigger_gate::lexicon`'s module doc), so this crate is the one place
//! that depends on both and drives them together as the documented
//! pipeline: segment -> tag -> group by language -> per-language lexicon.
//! No production code lives here; see `tests/` for the actual assertions.
