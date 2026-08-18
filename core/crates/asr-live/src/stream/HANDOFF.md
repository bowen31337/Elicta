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

Verified with `cargo test` and `cargo clippy` (24 passing tests, no
warnings) in a scratch crate mirroring this module tree plus the existing
`backend` module, since the crate-level `Cargo.toml`/`lib.rs` in this
worktree only registers `backend` and `tokens` as of this writing. That
run also turned up `fake.rs`'s `PrematureEndpointFakeBackend` missing a
`start_stream` impl (a pre-existing gap unrelated to `FirstPartialDelay` —
the trait requires it and nothing here had exercised the miss yet, since
the module isn't wired into `lib.rs`); fixed as a no-op alongside this
change so the module actually compiles.
