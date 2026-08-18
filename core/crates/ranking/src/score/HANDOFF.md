# score module — handoff (authority_match)

Implements PRD FR-4.7 ("weight candidate ranking by attendee decision
authority and domain -- surface questions the people actually in the room
can answer"), specifically the `w₃·authority_match` term of the ranking
formula (architecture §3.7: "score = w₁·trigger_match + w₂·coverage_urgency
+ w₃·authority_match + w₄·priority − w₅·recency_penalty − w₆·asked_penalty").

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

None -- `src/lib.rs` already wires `pub mod score;`. `score::authority_match`
has no dependency on any other module in this crate.

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
- `mod.rs` -- declares `pub mod authority_match;` and re-exports
  `authority_match_term`, `DEFAULT_AUTHORITY_MATCH_WEIGHT`.

Tests added: 6 (a fully-matched candidate scores higher than an unmatched
one -- the FR-4.7 acceptance criterion itself; a partially-matched
candidate scores strictly between fully-matched and unmatched; a candidate
with no authority requirement scores the full term, matching
`compute_candidate_authority_match`'s "no requirement is universally
answerable" contract; a zero weight makes the term ignore the match
entirely, proving weights are genuinely configuration and not baked in;
the term scales linearly with weight; under the default weight, a higher
match never scores lower).

## What's not done here

- Anything beyond the minimal scaffold: no other crate metadata
  (description, dependencies, lints) was added to `Cargo.toml`, and
  `src/lib.rs` declares nothing beyond `pub mod score;`. Whoever adds the
  next module to this crate (e.g. the phrasing/slot-instantiation half of
  architecture §3.7) should extend `lib.rs` with an additional `pub mod`
  line, not restructure what's here.
- Deriving `authority_match` itself from an attendee roster -- already
  done, out of this crate's footprint entirely:
  `apps/service/.../compiler/techniques/authority_matching.py`'s
  `compute_candidate_authority_match` and
  `persist_candidate_authority_matches`.
- The other five terms of the ranking formula (`trigger_match`,
  `coverage_urgency`, `priority`, `recency_penalty`, `asked_penalty`) and
  the top-level function that sums all six into one candidate score --
  separate, not-yet-planned-here concerns; this file only proves the
  `authority_match` term's own contribution is correctly signed and scaled.
- Filtering candidates whose `requires` prerequisites are unsatisfied
  before scoring (architecture §3.7) -- a separate concern from any single
  term's value.
- Loading actual candidate/meeting data and calling `authority_match_term`
  from the live ranking pipeline -- belongs to whichever crate/module owns
  that orchestration once the crate scaffold exists.
