# score module — handoff (authority_match, trigger_match, coverage_urgency, priority, candidate_score)

Implements two features layered in this module over time:

1. PRD FR-4.7 ("weight candidate ranking by attendee decision authority and
   domain -- surface questions the people actually in the room can
   answer"), specifically the `w₃·authority_match` term of the ranking
   formula (architecture §3.7: "score = w₁·trigger_match +
   w₂·coverage_urgency + w₃·authority_match + w₄·priority −
   w₅·recency_penalty − w₆·asked_penalty") -- `authority_match.rs`.
2. "System scores each candidate as a pure function of trigger match,
   coverage urgency, authority match, and priority. Done when every
   candidate emits a score" -- `trigger_match.rs`, `coverage_urgency.rs`,
   `priority.rs`, and `candidate_score.rs`, which sums all four into one
   per-candidate total. This feature's scope is explicitly the four terms
   its own description names -- `recency_penalty` and `asked_penalty` are
   left out on purpose, not overlooked; see "What's not done here."

`core/crates/ranking` did not exist anywhere else in this repo before this
feature (no `Cargo.toml`, no `src/lib.rs`). This feature's own footprint is
`core/crates/ranking/src/score/**` only, and the original intent (mirroring
`core/crates/language/src/numerals/HANDOFF.md`'s precedent, where that
module's first feature predated its crate's scaffold and left the scaffold
to whoever created it next) was to leave `Cargo.toml`/`src/lib.rs` out of
scope here too. That is not viable here: the root `Cargo.toml`'s workspace
`members` already globs `core/crates/*`, and every other crate under
`core/crates/` (`language`, `trigger-gate`, `capture`, `asr-live`, `wer`)
already exists with a real `Cargo.toml` -- so merely creating the
`core/crates/ranking/` directory (unavoidable, since `src/score/**` has to
live somewhere) without a manifest breaks `cargo check --workspace`/`cargo
test --workspace` for every crate in the repo, not just this one. Minimal
`Cargo.toml` (name `ranking`, no dependencies) and `src/lib.rs`
(`pub mod score;` only) were added for that reason, not because this
feature's scope includes the crate as a whole -- verified with `cargo test
--workspace` and `cargo clippy --workspace --all-targets -- -D warnings`
from the repo root, both clean, 6/6 new tests pass, no other crate's output
changed.

## Wiring needed

None -- `src/lib.rs` already wires `pub mod score;`. `mod.rs` now declares
`pub mod candidate_score;`, `pub mod coverage_urgency;`, `pub mod priority;`,
and `pub mod trigger_match;` alongside the existing `pub mod
authority_match;`. `authority_match`, `trigger_match`, `coverage_urgency`,
and `priority` are each independent of one another and of `candidate_score`
-- `candidate_score` is the only module here with an intra-crate
dependency, importing each term function from its sibling module to sum
them.

## What's here

- `authority_match.rs` -- `authority_match_term(authority_match: f32,
  weight: f32) -> f32`, the `w₃·authority_match` term, plus
  `DEFAULT_AUTHORITY_MATCH_WEIGHT` (an uncalibrated placeholder, pending
  tuning against the replay harness per architecture §9). Takes the
  already-computed per-candidate `authority_match` value as a plain `f32`
  rather than an attendee roster -- see the file's doc comment for why:
  `apps/service/.../compiler/techniques/authority_matching.py`'s
  `compute_candidate_authority_match` already derives that value against a
  meeting's actual attendees (PRD FR-3.10's role / business_function /
  decision_authority / domain_expertise taxonomy), and that module's own
  docstring is explicit that ranking should read the resulting plain number
  rather than re-derive it from the roster on every score. Architecture
  §3.7 independently requires the ranking formula to be a "pure function,
  no I/O beyond the local index," which rules out this module fetching or
  matching against a roster itself.
- `trigger_match.rs` -- `trigger_match_term(trigger_match: f32, weight: f32)
  -> f32`, the `w₁·trigger_match` term, plus `DEFAULT_TRIGGER_MATCH_WEIGHT`.
  Takes the already-computed cosine similarity as a plain `f32` -- that
  value is `core/crates/bank`'s `retrieval::cosine::RankedCandidate::score`,
  and that module's own `HANDOFF.md` says explicitly "this module's cosine
  score is one input to [ranking's] `trigger_match`/similarity term, not
  the final candidate score." Same shape as `authority_match_term`: linear,
  positive-signed, scales with `weight`.
- `coverage_urgency.rs` -- `coverage_urgency_term(coverage_urgency: f32,
  weight: f32) -> f32`, the `w₂·coverage_urgency` term ("unfilled section ×
  time pressure", architecture §3.7), plus
  `DEFAULT_COVERAGE_URGENCY_WEIGHT`. Also takes an already-computed plain
  `f32`, same "pure function, no I/O" reasoning as the other terms -- but
  unlike `authority_match`/`trigger_match`, no coverage-tracking module
  exists yet anywhere in this repo to name as that value's producer; this
  file is written against the architectural contract, not a concrete
  caller, and whoever builds that tracker owns producing a value in this
  shape.
- `priority.rs` -- `priority_term(priority: i64, weight: f32) -> f32`, the
  `w₄·priority` term, plus `DEFAULT_PRIORITY_WEIGHT`. The odd one out among
  the four: `priority` is stored ascending, 1..N, lower-is-better
  (`store::BankCandidate::priority`'s own doc comment), but this term must
  enter the ranking sum positively-correlated with rank, so it inverts
  (`weight / priority`) rather than scaling directly. A non-positive
  `priority` (violating every producer's `>= 1` contract) scores `0.0`
  instead of dividing by zero, matching `retrieval::cosine::
  cosine_similarity`'s "malformed input degrades to ranked last, never
  panics" precedent.
- `candidate_score.rs` -- `CandidateScoreInputs` (the four raw per-candidate
  values), `ScoreWeights` (the four `w₁..w₄` weights) and `DEFAULT_WEIGHTS`,
  `CandidateScore` (id + total score), `score_candidate(inputs, weights) ->
  f32` (sums the four terms for one candidate), and
  `score_candidates(candidates: &[(String, CandidateScoreInputs)], weights)
  -> Vec<CandidateScore>` (scores every candidate, order-preserving, one
  `CandidateScore` per input -- the literal "every candidate emits a score"
  acceptance criterion). Does not sort or pick a winner; that's a separate,
  downstream concern this function doesn't decide, mirroring how
  `retrieval::prerequisite`'s filter and `retrieval::cosine`'s ranker stay
  decoupled from each other in the sibling `bank` crate.
- `mod.rs` -- declares `pub mod authority_match;`, `pub mod
  candidate_score;`, `pub mod coverage_urgency;`, `pub mod priority;`, `pub
  mod trigger_match;`, and re-exports every public item from each.

Tests added: 6 for `authority_match.rs` (a fully-matched candidate scores
higher than an unmatched one -- the FR-4.7 acceptance criterion itself; a
partially-matched candidate scores strictly between fully-matched and
unmatched; a candidate with no authority requirement scores the full term,
matching `compute_candidate_authority_match`'s "no requirement is
universally answerable" contract; a zero weight makes the term ignore the
match entirely, proving weights are genuinely configuration and not baked
in; the term scales linearly with weight; under the default weight, a
higher match never scores lower). 5 for `trigger_match.rs` (mirrors
`authority_match.rs`'s shape, plus an orthogonal-candidate case since
cosine similarity's range spans negative values `authority_match` never
does). 5 for `coverage_urgency.rs` (same shape again). 6 for `priority.rs`
(best-priority-scores-higher, strict monotonic decrease as raw priority
grows, zero weight ignores it, linear scaling, non-positive priority
degrades to `0.0` instead of panicking, default weight never lets a better
priority score lower). 6 for `candidate_score.rs`: every candidate in the
input emits a score (length-preserving, the feature's own acceptance
criterion, made concrete), order/id preservation, an empty input emits an
empty output, the total is exactly the sum of the four terms (checked
against a hand-computed expected value), a maximally-matched candidate
outscores a maximally-unmatched one even at an extreme priority gap, and
zeroing one term's weight changes the total by exactly that term's own
contribution and no more -- proving the four terms are summed independently
rather than interacting.

## What's not done here

- Anything beyond the minimal scaffold: no other crate metadata
  (description, dependencies, lints) was added to `Cargo.toml`, and
  `src/lib.rs` declares nothing beyond `pub mod score;`. Whoever adds the
  next module to this crate (e.g. the phrasing/slot-instantiation half of
  architecture §3.7) should extend `lib.rs` with an additional `pub mod`
  line, not restructure what's here.
- `recency_penalty` and `asked_penalty`, the remaining two terms of
  architecture §3.7's full six-term formula ("similar nudge surfaced
  recently" and "operator tapped 'Asked it' on this thread") -- out of this
  feature's stated scope ("trigger match, coverage urgency, authority
  match, and priority"), and each needs a state source (recently-surfaced
  nudges, "Asked it" taps) that doesn't exist anywhere in this repo yet.
  `candidate_score::score_candidate`/`score_candidates` sum exactly the
  four terms this feature names; extending the sum to six terms once those
  two exist is a follow-up feature's job, not a gap in this one.
- Producing a real `coverage_urgency` value -- no coverage tracker (which
  template sections are filled, how much meeting time remains) exists
  anywhere in this repo; `coverage_urgency_term` and `CandidateScoreInputs`
  are written against the contract that value will eventually satisfy.
- Deriving `authority_match` itself from an attendee roster -- already
  done, out of this crate's footprint entirely:
  `apps/service/.../compiler/techniques/authority_matching.py`'s
  `compute_candidate_authority_match` and
  `persist_candidate_authority_matches`.
- Filtering candidates whose `requires` prerequisites are unsatisfied
  before scoring (architecture §3.7) -- already done, out of this crate
  entirely: `core/crates/bank`'s `retrieval::prerequisite::
  filter_unsatisfied_prerequisites`.
- Sorting scored candidates or picking a winner -- `score_candidates`
  returns one score per input in input order; ranking/selecting from that
  list is a separate, not-yet-planned-here concern.
- Loading actual candidate/meeting data, assembling `CandidateScoreInputs`
  from `store::BankCandidate` plus a live cosine score and coverage state,
  and calling `score_candidates` from the live ranking pipeline -- belongs
  to whichever crate/module owns that orchestration; no code in this crate
  wires `store`/`retrieval` to `score` yet, the same gap
  `retrieval/HANDOFF.md` already flags on its side of the boundary.
