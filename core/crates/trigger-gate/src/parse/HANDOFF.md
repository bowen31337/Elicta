# parse module — handoff

Implements "System emits a `TriggerEvent` carrying kind, utterance_id, span,
and the minimum token confidence across that span" — architecture §3.5's
literal output shape for the trigger gate:

```rust
pub struct TriggerEvent {
    pub kind: TriggerKind,
    pub utterance_id: Uuid,
    pub span: Option<Range<usize>>, // byte range of the offending phrase
    pub confidence: f32,            // minimum token confidence across the span
}
```

A prior feature in this same directory ("System suppresses a nudge when the
trigger span itself falls below the per-word confidence threshold", PRD
NFR-5.6) had already landed a `TriggerEvent` — but as an enum,
`Fired { span, confidence }` / `Suppressed { span, confidence, reason }`,
with no `utterance_id` and no top-level `kind` field. This change reshapes
it into the struct architecture §3.5 actually specifies, folding that
enum's two variants into the new `kind: TriggerKind` field
(`TriggerKind::Fired` / `TriggerKind::Suppressed(SuppressionReason)`) so no
suppression behaviour or test coverage from that feature was lost — only
restructured.

`core/crates/trigger-gate/src/lib.rs` already had `pub mod parse;`; no
scaffold changes needed here.

## What's here

- `event.rs` — `TriggerEvent` (struct: `kind`, `utterance_id`, `span`,
  `confidence`), `TriggerKind` (`Fired` | `Suppressed(SuppressionReason)`),
  `SuppressionReason` (`SpanConfidenceBelowThreshold { confidence,
  threshold }`, PRD NFR-5.6), and `UtteranceId`.
  `UtteranceId` is a `String` alias, not architecture's literal `Uuid` —
  this crate has no dependency on the `uuid` crate or on `asr-live` (which
  mints real utterance ids as `String` too, see
  `core/crates/asr-live/src/backend/event.rs`), and nothing here needs to
  parse or generate an id, only carry one through. Re-point at a shared
  type once crate wiring links `trigger-gate` to whatever mints utterance
  ids at runtime.
  `span` is `Option<Range<usize>>` per architecture §3.5, for trigger kinds
  not tied to one specific span; every kind this crate produces today
  (`Fired`, `Suppressed`) always sets it to `Some`.
  `TriggerKind` only has two variants because this crate only implements
  span-confidence gating so far — the trigger-type taxonomy architecture
  §3.5 lists (unquantified adjective, unnamed actor, contradiction, novel
  entity, coverage-gap-plus-drift) is not plumbed into this module at all;
  `gate_span_confidence`'s inputs (a span, its word confidences, a
  threshold) carry no notion of *which* trigger rule matched. Whoever wires
  `lexicon::LexiconMatch` into this event will need to either extend
  `TriggerKind` with those variants or thread trigger-type information
  through as a new field — not decided here.
- `gate.rs` — `gate_span_confidence(utterance_id, span, word_confidences,
  min_span_confidence)`. Same reduction logic as before (minimum, not
  average, of `word_confidences`; a span backed by zero words is suppressed
  at confidence `0.0`) — only the return shape and the new `utterance_id`
  parameter changed. `utterance_id` is a pure pass-through: it is not
  derived from the span or its confidences, only carried onto the
  resulting event (see
  `two_events_from_different_utterances_carry_their_own_utterance_id`).
- `mod.rs` — module doc and re-exports (`TriggerEvent`, `TriggerKind`,
  `SuppressionReason`, `UtteranceId`, `gate_span_confidence`).

## Why this satisfies "emits a TriggerEvent carrying kind, utterance_id,
span, and the minimum token confidence across that span"

`TriggerEvent` is a struct, not an enum, with exactly those four fields —
matching architecture §3.5's own type signature rather than approximating
it. `gate_span_confidence` cannot construct one without all four: `kind` is
computed from the confidence-vs-threshold comparison, `utterance_id` is a
required parameter with no default, `span` is always `Some(span)`, and
`confidence` is the same minimum-of-word-confidences value in every case
(fired or suppressed) — architecture §3.5's "for every event, fired or
not". `gate.rs`'s existing suppression tests (`a_span_below_threshold_...`,
`a_single_low_confidence_word_...`, `confidence_exactly_at_the_threshold_...`,
`a_span_backed_by_no_words_...`, `a_zero_threshold_...`) were updated to the
new struct shape and still pass, pinning the same boundary behaviour as
before; the new
`two_events_from_different_utterances_carry_their_own_utterance_id` test
covers the field this feature actually adds.

## Wiring needed

`core/crates/trigger-gate/src/lib.rs` is unchanged (`pub mod lexicon; pub
mod parse;`). Not yet wired here, left for whoever integrates the full gate
loop (feature 141) or a sibling `ratelimit/` submodule:

- Extending `TriggerKind` (or adding a separate field) to carry *which*
  trigger rule matched (unquantified adjective, unnamed actor, etc.) once
  `lexicon::LexiconMatch` is threaded into this module — today `TriggerKind`
  only distinguishes fired vs. suppressed, not trigger category.
- Sourcing a real `utterance_id` at the call site — this feature only
  proves the value is carried through untouched, not where it comes from
  at runtime.
- Turning a `lexicon::LexiconMatch` plus the `TaggedToken`s it was matched
  from into the `(span, word_confidences)` `gate_span_confidence` takes —
  `LexiconMatch` still carries a single `token_index`, not a byte range or
  a confidence.
- The actual `min_span_confidence` threshold value used at runtime, and
  FR-5.7's rolling pass-rate self-regulation — both unchanged from the
  prior feature's handoff notes, still out of scope here.

Verified standalone: `cargo test -p trigger-gate` — 23/23 pass (16 prior
`lexicon` tests untouched, 6 prior `parse` tests updated to the new shape,
1 new `parse` test); `cargo clippy -p trigger-gate --all-targets -- -D
warnings` — clean; `cargo fmt -p trigger-gate -- --check` — clean.
