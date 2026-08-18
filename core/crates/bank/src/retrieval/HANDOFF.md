# retrieval module — handoff

Implements two features layered in this module over time:

1. "System retrieves matching candidates by brute-force cosine over the
   bank in under 20 milliseconds. Done when each query emits a ranked
   candidate list" (architecture §3.6: "Local SQLite with a vector index
   (sqlite-vec, or a flat index -- at a few hundred candidates, brute-force
   cosine is sub-millisecond and an approximate index is unnecessary
   complexity)") -- `cosine.rs`.
2. "System filters out candidates whose prerequisite ids in the `requires`
   column are unsatisfied before scoring runs. Done when an unsatisfied
   prerequisite emits no candidate" (architecture §3.7: "Candidates whose
   `requires` prerequisites are unsatisfied are filtered before scoring")
   -- `prerequisite.rs`.

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

None -- `src/lib.rs` already wires `pub mod retrieval;`, and `mod.rs`
declares `pub mod prerequisite;` alongside `pub mod cosine;`. Neither
`retrieval::cosine` nor `retrieval::prerequisite` depends on the other or on
any other module -- a caller runs `filter_unsatisfied_prerequisites` first
and feeds only the survivors into `retrieve_ranked_candidates`, but nothing
in either function enforces that ordering itself.

## What's here

- `cosine.rs` -- `CandidateVector` (id + embedding), `RankedCandidate` (id +
  score), and `retrieve_ranked_candidates(query: &[f32], bank:
  &[CandidateVector]) -> Vec<RankedCandidate>`. Scores every candidate in
  the bank by cosine similarity to `query` and returns them sorted
  descending -- the full ranked list, not top-k, matching architecture
  §3.6's brute-force-over-everything design at this scale. A dimension
  mismatch or an all-zero embedding scores `0.0` rather than panicking or
  producing `NaN`, so one malformed row can't crash the retrieval hot path.
- `prerequisite.rs` -- `PrerequisiteCandidate` (id + `requires`, the
  candidate ids this candidate depends on) and
  `filter_unsatisfied_prerequisites(candidates: &[PrerequisiteCandidate],
  satisfied: &HashSet<String>) -> Vec<PrerequisiteCandidate>`. Keeps a
  candidate only if every id in its `requires` is present in `satisfied`;
  an empty `requires` list always passes. Drops a candidate with even one
  unsatisfied prerequisite entirely (no candidate emitted for it), rather
  than returning it flagged or scored `0.0` -- the acceptance criterion is
  literally "an unsatisfied prerequisite emits no candidate," not "emits a
  suppressed one." Doesn't validate that a `requires` id refers to a real
  candidate or reject self-reference -- `apps/service`'s
  `compiler/tagging/tag_candidates.py` already guarantees both at compile
  time, before a candidate ever reaches this on-device store.
- `mod.rs` -- declares `pub mod cosine;` and `pub mod prerequisite;`, and
  re-exports `CandidateVector`, `RankedCandidate`,
  `retrieve_ranked_candidates`, `PrerequisiteCandidate`,
  `filter_unsatisfied_prerequisites`.

Tests added: 10 for `cosine.rs`, covering the ranked-list contract (every
candidate appears, sorted descending, identical/orthogonal/opposite vectors
score 1.0/0.0/-1.0), the two "must not crash" edge cases (zero vector,
mismatched dimensions both score `0.0` instead of panicking or NaN-ing),
magnitude invariance (cosine ignores vector scale), and a 5000-candidate
scan (an order of magnitude above architecture §3.6's ~200-candidate
sizing) to prove the brute-force scan itself handles bank sizes well past
what this feature needs, without asserting a literal wall-clock bound in CI
-- same reasoning `trigger-gate/src/lexicon/HANDOFF.md` used to defer its
own `<20ms` proof to a benchmark/replay harness rather than a timing
assertion in the test suite. 9 more for `prerequisite.rs`: the acceptance
criterion itself (an unsatisfied prerequisite emits no candidate), no
requirements always passes, a satisfied single prerequisite passes,
multi-requirement candidates need *every* id satisfied (partial isn't
enough) both in the failing and passing direction, satisfied/unsatisfied
candidates are partitioned independently within one call, survivor order
is preserved, an empty candidate list, and irrelevant entries in
`satisfied` are harmless.

## What's not done here

- Decoding the `candidate.embedding` `BLOB` column into `Vec<f32>` -- this
  module takes already-decoded `f32` vectors; whoever wires the local
  SQLite index (architecture §3.6) owns the BLOB↔`Vec<f32>` conversion.
- Embedding the live query utterance itself -- out of scope; this module
  only ranks an already-embedded query against an already-embedded bank.
- Deciding which candidate ids count as "satisfied" -- `prerequisite.rs`
  only applies the filter given a `satisfied` set; tracking which
  candidates the operator has already been asked/answered (PRD FR-6.7's
  "Asked it") and building that set belongs to whichever module owns
  session/meeting runtime state, out of this crate's footprint.
- The rest of the `w₁..w₆` ranking formula (architecture §3.7) beyond the
  `requires` filter -- a separate, downstream stage in `core/crates/ranking`.
  This module's cosine score is one input to that formula's
  `trigger_match`/similarity term, not the final candidate score.
- Converting `store::BankCandidate` (the on-device row shape, with its own
  `requires: Vec<String>` field) into `PrerequisiteCandidate` or
  `CandidateVector` -- no code in this crate wires `store` to `retrieval`
  yet; whoever assembles the live retrieval call owns that mapping.
- A literal wall-clock `<20ms` benchmark -- proved structurally (brute-force
  single-pass scan, no per-candidate allocation beyond the output `Vec`)
  and exercised at 25x the PRD's ~200-candidate sizing, but not asserted as
  a timing test; see architecture §9's replay harness for where an actual
  latency budget gets measured.
