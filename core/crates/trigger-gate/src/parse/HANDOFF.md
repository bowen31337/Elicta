# parse module — handoff

Implements the "span-confidence suppression" feature `lexicon/HANDOFF.md`
called out as out of scope for itself: "System suppresses a nudge when the
trigger span itself falls below the per-word confidence threshold" (PRD
NFR-5.6). Done when a low-confidence span emits a suppressed trigger event
carrying its reason.

`core/crates/trigger-gate/src/lib.rs` already existed (`pub mod lexicon;`)
from an earlier workspace-scaffold change, so this change only adds
`pub mod parse;` alongside it — no new crate scaffold needed.

## What's here

- `event.rs` — `TriggerEvent`, the trigger gate's uniform output shape
  (architecture §3.5): `Fired { span, confidence }` or
  `Suppressed { span, confidence, reason }`. `SuppressionReason` currently
  has one variant, `SpanConfidenceBelowThreshold { confidence, threshold }`
  (NFR-5.6) — left as an enum rather than a single struct since architecture
  §3.5 implies other tiers (e.g. FR-5.7's pass-rate self-regulation) may add
  their own suppression reasons later without changing `TriggerEvent`'s
  shape.
- `gate.rs` — `gate_span_confidence(span, word_confidences, min_span_confidence)`.
  Takes every per-word confidence the candidate span covers and reduces it
  to the minimum itself, matching architecture §3.5's own definition of
  `TriggerEvent.confidence` as "the minimum token confidence across the
  span" — deliberately not an average, since one misheard word inside an
  otherwise-clean multi-word span (`quantify "fast"` for "vast") is exactly
  the case NFR-5.6 exists to catch, and an average a single bad word can't
  move far would defeat the point. A span backed by zero words is
  suppressed with confidence `0.0` rather than treated as automatically
  trustworthy (there is nothing here to be confident about).
- `mod.rs` — module doc and re-exports (`TriggerEvent`, `SuppressionReason`,
  `gate_span_confidence`).

## Why this satisfies "a low-confidence span emits a suppressed trigger
event carrying its reason"

`gate_span_confidence` is a pure function from a span's own word
confidences to a `TriggerEvent` — there is no code path where a span whose
minimum confidence is below `min_span_confidence` produces `Fired` instead
of `Suppressed`, and `Suppressed` cannot be constructed without a `reason`
(it is a required struct field, not optional). `gate.rs`'s
`a_span_below_threshold_is_suppressed_and_carries_its_reason` and
`a_single_low_confidence_word_suppresses_an_otherwise_confident_span` tests
cover this directly; `confidence_exactly_at_the_threshold_is_not_suppressed`
and `a_zero_threshold_never_suppresses` pin the boundary so the comparison
can't silently drift to `<=` or become inverted later.

## Wiring needed

`core/crates/trigger-gate/src/lib.rs` now has:

```rust
pub mod lexicon;
pub mod parse;
```

No other integration is required by this feature's own "Done when"
criterion. Not yet wired here, left for whoever integrates the full gate
loop (feature 141) or a sibling `ratelimit/` submodule:

- Turning a `lexicon::LexiconMatch` plus the `TaggedToken`s it was matched
  from into the `(span, word_confidences)` this module's function takes —
  today `LexiconMatch` carries a single `token_index`, not a byte range or a
  confidence, so that adapter is a few lines wherever the two modules are
  first wired together, not a decision made here.
- The actual `min_span_confidence` threshold value used at runtime — PRD
  NFR-5.6 does not specify a number, and no other feature in this worktree
  has set one either (checked: no config/constant defines it anywhere in
  the repo). `gate_span_confidence` takes it as a parameter, same
  convention as `LexiconRouter::run`'s `min_tag_confidence`.
- FR-5.7's rolling pass-rate self-regulation (raising thresholds when pass
  rate exceeds ~10% of utterances) — a stateful concern layered on top of
  this stateless per-span comparison, out of scope for this feature.

Verified standalone: `cargo test -p trigger-gate` — 22/22 pass (16 prior
`lexicon` tests untouched, 6 new `parse` tests); `cargo clippy -p
trigger-gate --all-targets -- -D warnings` — clean; `cargo fmt -p
trigger-gate -- --check` — clean.
