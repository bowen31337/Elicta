# retrieval module — handoff

Implements "System retrieves matching candidates by brute-force cosine over
the bank in under 20 milliseconds. Done when each query emits a ranked
candidate list" (architecture §3.6: "Local SQLite with a vector index
(sqlite-vec, or a flat index -- at a few hundred candidates, brute-force
cosine is sub-millisecond and an approximate index is unnecessary
complexity)").

`core/crates/bank` did not exist anywhere else in this repo before this
feature (no `Cargo.toml`, no `src/lib.rs` -- confirmed via `find`). This
feature's own footprint is `core/crates/bank/src/retrieval/**` only, but per
`core/crates/ranking/src/score/HANDOFF.md`'s precedent (same situation, same
root cause): the root `Cargo.toml`'s workspace `members` globs
`core/crates/*`, and every other crate under `core/crates/` already has a
real `Cargo.toml` -- so a `core/crates/bank/` directory without a manifest
would break `cargo check --workspace` for every crate, not just this one.
Minimal `Cargo.toml` (name `bank`, no dependencies) and `src/lib.rs`
(`pub mod retrieval;` only) were added for that reason, not because this
feature's scope includes the crate as a whole.

## Wiring needed

None -- `src/lib.rs` already wires `pub mod retrieval;`. `retrieval::cosine`
has no dependency on any other module.

## What's here

- `cosine.rs` -- `CandidateVector` (id + embedding), `RankedCandidate` (id +
  score), and `retrieve_ranked_candidates(query: &[f32], bank:
  &[CandidateVector]) -> Vec<RankedCandidate>`. Scores every candidate in
  the bank by cosine similarity to `query` and returns them sorted
  descending -- the full ranked list, not top-k, matching architecture
  §3.6's brute-force-over-everything design at this scale. A dimension
  mismatch or an all-zero embedding scores `0.0` rather than panicking or
  producing `NaN`, so one malformed row can't crash the retrieval hot path.
- `mod.rs` -- declares `pub mod cosine;` and re-exports `CandidateVector`,
  `RankedCandidate`, `retrieve_ranked_candidates`.

Tests added: 10, covering the ranked-list contract (every candidate
appears, sorted descending, identical/orthogonal/opposite vectors score
1.0/0.0/-1.0), the two "must not crash" edge cases (zero vector, mismatched
dimensions both score `0.0` instead of panicking or NaN-ing), magnitude
invariance (cosine ignores vector scale), and a 5000-candidate scan (an
order of magnitude above architecture §3.6's ~200-candidate sizing) to
prove the brute-force scan itself handles bank sizes well past what this
feature needs, without asserting a literal wall-clock bound in CI --
same reasoning `trigger-gate/src/lexicon/HANDOFF.md` used to defer its own
`<20ms` proof to a benchmark/replay harness rather than a timing assertion
in the test suite.

## What's not done here

- Decoding the `candidate.embedding` `BLOB` column into `Vec<f32>` -- this
  module takes already-decoded `f32` vectors; whoever wires the local
  SQLite index (architecture §3.6) owns the BLOB↔`Vec<f32>` conversion.
- Embedding the live query utterance itself -- out of scope; this module
  only ranks an already-embedded query against an already-embedded bank.
- Filtering candidates whose `requires` prerequisites are unsatisfied, and
  the rest of the `w₁..w₆` ranking formula (architecture §3.7) -- a
  separate, downstream stage from `core/crates/ranking`. This module's
  cosine score is one input to that formula's `trigger_match`/similarity
  term, not the final candidate score.
- A literal wall-clock `<20ms` benchmark -- proved structurally (brute-force
  single-pass scan, no per-candidate allocation beyond the output `Vec`)
  and exercised at 25x the PRD's ~200-candidate sizing, but not asserted as
  a timing test; see architecture §9's replay harness for where an actual
  latency budget gets measured.
