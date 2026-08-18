# stream module — handoff

Implements architecture §14.2 / the aggressive-endpointing trade it
describes: "moving \[the silence threshold\] to 400ms buys 200ms ... the
cost is more premature endpoints mid-sentence, which the trigger gate must
tolerate by re-evaluating when a continuation arrives." This module is that
tolerance, made real rather than just documented: it sits between
`backend::TranscriptionBackend::poll_events` and whatever consumes its
output, and turns a premature endpoint plus its continuation back into one
corrected utterance before anything downstream reacts to the pair twice.

Self-contained under this directory; deliberately does not touch
`core/crates/asr-live/Cargo.toml` or `core/crates/asr-live/src/lib.rs` — per
`backend/HANDOFF.md`, those are owned by the crate scaffold, which already
registered this crate's other two submodules (`backend`, `tokens`) the same
way.

## Wiring needed (one line, in the shared `lib.rs`)

Whoever owns `core/crates/asr-live/src/lib.rs` needs to add:

```rust
pub mod stream;
```

This module depends only on `super::backend` (same crate, already wired)
and has no external crate dependencies, so no `Cargo.toml` changes are
required for it specifically.

## What's here

- `event.rs` — `StreamEvent`, the enum a caller should react to instead of
  `TranscriptionEvent` once re-evaluation is in the loop: `Interim` and
  `Final` forward the backend's own event unchanged; `Correction` is the
  new case, carrying the merged, corrected utterance plus the id of the
  utterance it supersedes.
- `reevaluate.rs` — `UtteranceReevaluator`, the stateful piece that holds
  the most recently finalised utterance per `StreamId` and merges it with
  the next one when the gap between them is within
  `continuation_window` (`DEFAULT_CONTINUATION_WINDOW` = 1600ms, chosen
  above the documented `max_turn_silence` range of 1280-1536ms so a
  genuine premature-endpoint pause is caught without also catching a real
  turn change). `apply(TranscriptionEvent) -> StreamEvent` is the whole
  public surface; call it once per event, in arrival order, per session.
- `fake.rs` — `PrematureEndpointFakeBackend`, a scripted
  `TranscriptionBackend` (mirroring `backend::fake`'s pattern: exported,
  not test-only) reproducing exactly the scenario this module exists for —
  a mid-sentence cut, a continuation that closes it, and a later, wholly
  unrelated utterance that must never be merged in. Used both to unit-test
  this module and as a fixture whoever wires the trigger gate can develop
  against before a real vendor connection exists.
- `first_partial_delay.rs` — `FirstPartialDelay` (PRD FR-5.9, architecture
  §14.2's `interruption_delay` discussion): the delay this system requests
  when opening a stream, so the engine emits its first partial as early as
  it allows and speculative drafting gets the widest possible window
  between first partial and endpoint. `FirstPartialDelay::floor()` /
  `FIRST_PARTIAL_DELAY` is the engine's documented minimum (architecture
  §14.2: "0-1000ms") — what this system actually requests by default —
  and `FirstPartialDelay::new` validates any override stays inside that
  range rather than silently sending the engine a value it doesn't
  support.
- `endpointing_threshold.rs` — `EndpointingThresholds` (PRD FR-2.2): the
  endpointing silence threshold as configuration, defaulting to 600ms
  (`DEFAULT_ENDPOINTING_THRESHOLD`) and tunable independently per
  `CaptureMode` (`ManagedParticipant`, `Loopback`, `LineIn`,
  `AcousticFallback` — PRD §10's priority-ordered capture options).
  `for_mode`/`set` is the whole public surface: reading a mode that was
  never tuned returns the default, and `set` persists an override for that
  mode only, leaving every other mode's value alone. `CaptureMode` is
  defined locally rather than imported from `capture::device::kind`'s
  `AudioSourceKind` (same four paths, different names) to keep this module
  dependency-free, the same reasoning `fake.rs` and `first_partial_delay.rs`
  already follow for this directory — see "Deliberately out of scope"
  below for what unifying the two would take.
- `turn_silence.rs` — `TurnSilenceParameters` and `TuningReport`
  (architecture §14.2, T2). AssemblyAI's confidence/punctuation-based
  engines split what `EndpointingThresholds` treats as one FR-2.2 knob into
  two: `min_turn_silence`, which trades against latency the way a silence
  timer does, and `max_turn_silence`, the forced-end ceiling that governs
  the tail instead. `TurnSilenceParameters::universal_streaming_defaults`/
  `universal_3_5_pro_defaults` hold the documented per-engine defaults
  (400/1280ms; 400/1536ms, or 400/768ms with `speaker_labels`).
  `TuningReport::from_samples` is a tuning run: given a candidate
  `TurnSilenceParameters` and a batch of end-to-end speech-end-to-
  nudge-visible samples, it reports p50 and p95 as two independent
  `LatencyMeasurement`s against NFR-1's targets (`P50_LATENCY_TARGET`
  2000ms, `P95_LATENCY_TARGET` 3500ms) — "report both," never blended into
  one verdict, since a different knob governs each.
  `suggest_next_min_turn_silence` closes the loop for `min_turn_silence`
  only: step it down on a p50 miss, step it back up when there's a full
  step of headroom (fewer premature endpoints for the trigger gate to
  re-evaluate without giving back the budget), hold at the edge.
  `max_turn_silence` is never adjusted by tuning — it is the ceiling this
  run measures p95 against, not a parameter this run searches over; picking
  it is the vendor bake-off itself (see "Deliberately out of scope").
- `interim_latency.rs` — `check_interim_latency` (PRD FR-2.1). Every
  `InterimHypothesis` already carries `stream_id`, `text`, and `started_at`
  (`backend::event`); FR-2.1 additionally requires that the event actually
  reach a consumer within 400ms of the speech onset `started_at` names
  (`INTERIM_LATENCY_BUDGET`). `check_interim_latency(interim, observed_at)`
  is that check: `observed_at` is a stream-relative timestamp the caller
  supplies (this module has no clock of its own, the same reasoning
  `turn_silence.rs`'s `TuningReport::from_samples` takes a batch by value
  rather than instrumenting a live one), and the function returns the
  observed latency on success or an `InterimLatencyExceeded` — carrying
  `stream_id`, `started_at`, `observed_at`, and `over_by` — when the budget
  is missed. Distinct from `FirstPartialDelay` (FR-5.9): that module
  decides how soon this system *asks the engine* for a first partial; this
  one measures whether whatever partial actually arrived — first or a
  later revision — reached a consumer in time, independent of what delay
  was requested.

- `final_utterance_event.rs` — `FinalUtteranceEvent`/`on_endpoint` (PRD
  FR-2.3). `backend::FinalUtterance` already carries every field FR-2.3
  names (`id`, `stream_id`, `speaker`, `start`, `end`, `tokens` —
  `backend/event.rs`), plus two more (`text`, `audio_ref`) that are this
  crate's own bookkeeping rather than part of the FR-2.3 contract.
  `FinalUtteranceEvent` is the outbound shape with exactly FR-2.3's fields,
  `start`/`end` converted from `Duration` into `start_ms`/`end_ms`
  millisecond integers. `on_endpoint(&StreamEvent) -> Option<FinalUtteranceEvent>`
  is what a caller should call on every `StreamEvent` it observes: `None`
  for `Interim`, `Some` for both `Final` and `Correction` — a `Correction`
  is still an utterance closing on endpoint, just one continuation
  re-evaluation has already merged, and it carries the same FR-2.3 fields
  a `Final` would.

## Suggested integration point

Whatever currently drains `TranscriptionBackend::poll_events()` and hands
events to the trigger gate should instead route each event through one
`UtteranceReevaluator` per session (state is keyed internally by
`StreamId`, so one instance already handles every participant stream in a
managed-capture session) and react to the resulting `StreamEvent`. A
`StreamEvent::Correction` means: if the trigger gate already evaluated
`supersedes`'s text, retract that reaction — a corrected utterance is a
replacement, not an addition.

Whoever constructs a real vendor `TranscriptionBackend` (AssemblyAI in
particular — Deepgram's turn model doesn't expose an equivalent knob,
architecture §14.2's table) should request `FirstPartialDelay::floor()`'s
value as that connection's `interruption_delay` when opening the stream.
`TranscriptionBackend::start_stream` doesn't currently take this
parameter — extending it is `backend/`'s call, not this module's, since
`transcription_backend.rs` lives outside this directory.

Whoever knows a session's `capture::device::kind::AudioSourceKind` should
map it to this module's `CaptureMode` and call
`EndpointingThresholds::for_mode` for the value to request as that vendor
connection's silence-timer / turn-silence parameter (architecture §14.2's
table — which vendor field that is depends on the engine, same as the
`FirstPartialDelay` wiring above).

Whoever runs a real T2 bake-off against AssemblyAI should collect NFR-1's
speech-end-to-nudge-visible samples for a candidate `TurnSilenceParameters`
(`core/shared/telemetry`'s `TotalLatencyTracker` already records exactly
that distribution at runtime, independently of this crate) and feed them to
`TuningReport::from_samples` per candidate, iterating
`min_turn_silence` via `suggest_next_min_turn_silence` while holding
`max_turn_silence` at whichever documented ceiling the engine variant in
use provides.

Whoever wires the integration point above (`UtteranceReevaluator` draining
`poll_events()`) should call `check_interim_latency` on every
`StreamEvent::Interim` as it is observed, using that call site's own
stream-relative clock for `observed_at` — the same clock `InterimHypothesis
.started_at` and `FinalUtterance.start`/`.end` are already measured against
elsewhere in this crate. An `InterimLatencyExceeded` is a monitoring signal
(FR-2.1 compliance), not a reason to drop or delay the event itself — a
late interim is still the best hypothesis available and should still reach
the consumer.

Whoever wires the endpoint this crate ultimately emits over (a websocket to
a client, an internal queue, whatever transport FR-2.3's "on endpoint"
phrasing refers to) should call `on_endpoint` on every
`StreamEvent` coming out of `UtteranceReevaluator::apply` and send whatever
it returns `Some` for — skipping `None` (an `Interim`) — rather than
serialising `FinalUtterance` itself, so `text` and `audio_ref` never
accidentally leak across that boundary.

## Deliberately out of scope here

- Threading `FirstPartialDelay` through `TranscriptionBackend::start_stream`
  itself: that trait lives in `backend/`, outside this directory, and
  changing its signature is whoever owns that module's call. This module
  only decides and validates the value; wiring it onto a real handshake is
  the next step.
- Picking `continuation_window` per vendor/capture-mode is future-scoped
  work (architecture §14.2's T2 experiment); this module exposes it as a
  constructor parameter rather than hard-coding one number, with
  `DEFAULT_CONTINUATION_WINDOW` as a documented starting point, not a
  claim that it's been empirically tuned.
- Validating a configured `EndpointingThresholds` value against a
  per-vendor range, the way `FirstPartialDelay::new` validates
  `interruption_delay`: architecture §14.2 is explicit that Deepgram's
  silence timer and AssemblyAI's confidence/punctuation turn models "do
  not expose comparable knobs," so there is no single valid range to check
  against yet — that split is T2's bake-off, not FR-2.2's configuration
  surface.
- ~~Splitting the single FR-2.2 threshold into AssemblyAI's separate
  `min_turn_silence` (p50) / `max_turn_silence` (p95) knobs~~ — done, in
  `turn_silence.rs` (see below). `EndpointingThresholds` itself is
  unchanged: Deepgram's silence timer still only exposes the one FR-2.2
  threshold, so it models exactly that, per capture mode, not per vendor
  knob.
- Unifying this module's `CaptureMode` with `capture::device::kind::AudioSourceKind`
  into one shared type: that would need a shared crate dependency, which
  is a `Cargo.toml`/`lib.rs` change outside this directory (see the
  wiring note above) — until then the two enums are kept in sync by
  naming convention, not by the compiler.
- Merging retained audio segments (`AudioSegmentRef`) is not attempted —
  `merge` keeps the earlier utterance's `audio_ref` as-is rather than
  concatenating two opaque storage keys into a segment that doesn't exist.
  Whoever wires this against a real capture/storage layer should revisit
  whether the retained audio itself needs stitching to match the corrected
  text span.
- A correction chain longer than two utterances is handled (each new
  continuation supersedes the previous correction's id, not the original),
  but nothing here caps how long a chain of continuations can run before
  it should be treated as a genuinely new utterance regardless of gap —
  that's a policy decision for whoever tunes `continuation_window`, not a
  structural limitation of `UtteranceReevaluator`.
- Wiring `turn_silence.rs` to `core/shared/telemetry`'s
  `TotalLatencyTracker`/`LatencyHistogram` is not attempted: that crate
  already computes p50/p95 for the live end-to-end path (and already
  documents the same min-governs-p50/max-governs-p95 split in
  `total_latency.rs`), but depending on it from here is a `Cargo.toml`
  change outside this directory, the same reasoning that keeps
  `CaptureMode` undependent on `capture::device::kind`. `turn_silence.rs`
  therefore computes its own exact nearest-rank percentile over a batch
  passed in by value, appropriate for an offline tuning run, rather than
  sharing the histogram's bucketed runtime estimator.
- Choosing a numeric valid range for `min_turn_silence` to reject
  out-of-range overrides against, the way `FirstPartialDelay::new` does
  for `interruption_delay`: architecture §14.2 documents defaults for this
  knob, not a vendor-published valid range, so `TUNING_STEP` is a starting
  increment for the bake-off to refine, not a validated bound.
- Calling `check_interim_latency` from `UtteranceReevaluator::apply` itself
  is not attempted: `apply` has no notion of wall-clock/"now" today (its
  whole surface is `TranscriptionEvent -> StreamEvent`, no side clock
  parameter), and threading one through would change that method's
  signature for every existing caller, not just interims. Exposing the
  check as a free function callers can invoke themselves — the same shape
  `merge` already uses — avoids that, at the cost of nothing enforcing the
  check is actually called at every integration point (see "Suggested
  integration point" above).
- Deciding what happens on an `InterimLatencyExceeded` beyond returning it
  (alerting, metrics, telemetry export) is not attempted here — this
  module reports the violation with enough detail (`stream_id`,
  `started_at`, `observed_at`, `over_by`) for a caller to decide, the same
  reasoning `TuningReport` reports p50/p95 without prescribing what a
  caller does with a missed target.
- Actually serialising `FinalUtteranceEvent` onto a wire format (JSON,
  protobuf, whatever a real websocket/queue transport needs) is not
  attempted: no dependency in this crate provides that today (see
  `backend/HANDOFF.md`, "every crate in this workspace is std-only so
  far"), and picking a serialisation format is a decision for whoever
  actually owns the endpoint FR-2.3 emits over, not this module. This
  module's job ends at producing the right plain Rust value.

Verified with `cargo test` and `cargo clippy` (82 passing tests, no
warnings) in a scratch crate mirroring this module tree plus the existing
`backend` module, since the crate-level `Cargo.toml`/`lib.rs` in this
worktree only registers `backend` and `tokens` as of this writing. That
run also turned up `fake.rs`'s `PrematureEndpointFakeBackend` missing a
`start_stream` impl (a pre-existing gap unrelated to `FirstPartialDelay` —
the trait requires it and nothing here had exercised the miss yet, since
the module isn't wired into `lib.rs`); fixed as a no-op alongside this
change so the module actually compiles.
