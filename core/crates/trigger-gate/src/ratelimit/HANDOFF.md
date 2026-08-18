# ratelimit module — handoff

Implements "System maintains a rolling gate pass-rate counter across the
meeting window. Done when every evaluation emits the current pass rate" —
the counting half of PRD FR-5.7 / architecture §3.5's "the gate ... maintains
a rolling pass-rate counter and raises its own thresholds if pass rate
exceeds ~10% of utterances".

This is the sibling `ratelimit/` submodule the `parse/` module's own
HANDOFF.md flagged as still needed ("FR-5.7's rolling pass-rate
self-regulation ... still out of scope here").

## What's here

- `pass_rate.rs` — `PassRateCounter`, a rolling window over the most recent
  `window` gate evaluations:
  - `PassRateCounter::new(window)` — `window` is a count of evaluations, not
    a duration, matching FR-5.7's own phrasing of the budget as a fraction
    "of utterances". `window == 0` is treated as `1` (there is always
    somewhere to put the newest observation).
  - `record(&TriggerKind) -> f32` — folds one evaluation's outcome
    (`Fired`/`Suppressed`, from `crate::parse::TriggerKind`) into the
    window, evicting the oldest observation once full, and returns the pass
    rate *as it stands after this observation* — this is the "every
    evaluation emits the current pass rate" contract.
  - `record_fired(bool) -> f32` — same contract for callers that already
    have a bare fired/suppressed outcome and no `TriggerKind` to hand.
  - `pass_rate() -> f32` — the current rate without recording anything;
    `0.0` on an empty window.
- `mod.rs` — module doc and re-export (`PassRateCounter`).

`core/crates/trigger-gate/src/lib.rs` gained one line, `pub mod ratelimit;`
— the crate had no way to reach this module otherwise.

## Why this satisfies "maintains a rolling gate pass-rate counter ... every
evaluation emits the current pass rate"

`PassRateCounter` counts fired-vs-suppressed over a bounded, evicting window
(`the_window_only_rolls_over_the_most_recent_evaluations`), which is what
makes it *rolling* rather than a lifetime-of-the-meeting average that could
never recover from a noisy first few minutes. `record` cannot be called
without getting a fresh `f32` pass rate back
(`every_evaluation_gets_back_the_pass_rate_current_at_that_call`), so
"every evaluation emits the current pass rate" holds by construction: there
is no code path that records an outcome and gets nothing back.

## Deliberately out of scope

- **Raising the gate's own thresholds** in response to a high pass rate —
  architecture §3.5's "and raises its own thresholds if pass rate exceeds
  ~10%" is a separate concern that would *consume* `PassRateCounter`'s
  return value (e.g. feed it into `parse::gate_span_confidence`'s
  `min_span_confidence` parameter). Nothing here decides what a caller
  should do with the number; it only produces it.
- **Choosing the actual `window` size** used at runtime. No PRD/architecture
  text pins a concrete number of utterances for this window (unlike the
  unrelated 60–90s slow-lane transcript window), so this is left to
  whoever wires `PassRateCounter` into the live gate loop (feature 141).
- **Which evaluations get recorded.** `PassRateCounter` takes whatever
  `TriggerKind` it's handed; whether that's every utterance the gate sees or
  only some subset (e.g. architecture §3.5's "evaluating only utterances
  whose `speaker` is not `Operator`") is the caller's decision, made at the
  same integration point as the threshold response above.

Verified standalone: `cargo test -p trigger-gate` — 30/30 pass (23 prior
`lexicon`/`parse` tests untouched, 7 new `ratelimit` tests); `cargo clippy -p
trigger-gate --all-targets -- -D warnings` — clean; `cargo fmt -p
trigger-gate -- --check` — clean. Workspace-wide `cargo build` (including
`tests/e2e`, the only other crate depending on `trigger-gate`) still
succeeds.
