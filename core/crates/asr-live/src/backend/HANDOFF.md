# backend module — handoff

Implements architecture §3.2 / PRD FR-2.1-FR-2.3: the `TranscriptionBackend`
trait and the `TranscriptionEvent` shape (`InterimHypothesis`,
`FinalUtterance`, `Token`) that every streaming ASR vendor backend must
emit, so the trigger gate and everything else downstream is written once
against the trait and never against a concrete vendor. Self-contained under
this directory; deliberately does not touch `core/crates/asr-live/Cargo.toml`
or `core/crates/asr-live/src/lib.rs`, since those are owned by the crate
scaffold and shared with sibling plugin submodules (at least `stream/`, per
the feature list — the live event-emission side of this same crate).

## Wiring needed

Whoever owns `core/crates/asr-live/Cargo.toml` and
`core/crates/asr-live/src/lib.rs` needs to:

1. Create the crate scaffold (this crate doesn't exist on disk yet — no
   other feature under `asr-live` had created it as of this writing
   either). Mirror the existing crates' `Cargo.toml` shape exactly, e.g.
   `core/crates/capture/Cargo.toml` — package name `asr-live`, 2021
   edition, `src/lib.rs` as the library root, no external dependencies
   (every crate in this workspace is std-only so far).
2. Add to `src/lib.rs`:

   ```rust
   pub mod backend;
   ```

No other integration is required — `backend` has no dependency on any
other `asr-live` submodule and exposes a plain, synchronous trait plus the
value types it operates on:

```rust
pub use backend::{
    AudioSegmentRef, BackendError, FinalUtterance, InterimHypothesis, LanguageTag,
    SpeakerTag, StreamId, Token, TranscriptionBackend, TranscriptionEvent, UtteranceId,
};
```

## What's here

- `event.rs` — the value types architecture §3.2 specifies verbatim:
  `InterimHypothesis`, `FinalUtterance`, `Token`, plus the `TranscriptionEvent`
  enum that unions them into the one shape every backend emits. `StreamId`,
  `UtteranceId`, and `LanguageTag` are plain `String` aliases; `SpeakerTag`
  and `AudioSegmentRef` are minimal local types.
- `transcription_backend.rs` — the `TranscriptionBackend` trait itself
  (`send_audio` / `poll_events`, synchronous push/drain, no `async`) and
  `BackendError`.
- `fake.rs` — two scripted, non-networked test-double vendors
  (`ImmutablePartialFakeBackend`, mimicking AssemblyAI-style immutable
  partials, and `RevisablePartialFakeBackend`, mimicking Deepgram-style
  revised partials) used to prove the trait's core property: both emit the
  same `TranscriptionEvent` shape and can be driven by one function written
  generically over `impl TranscriptionBackend`, standing in for how the
  trigger gate will consume either vendor without knowing which one it is.
  These are exported, not test-only, so whoever wires the trigger gate can
  develop against them before a real vendor connection exists.

## Deliberately out of scope here

Everything about how a *real* vendor connection is opened and driven —
pre-opened websocket at capture start, keepalive frames, linear16 PCM
framing at 20-50ms, regional endpoint pinning, keyterm-prompting injection
— is separately scoped work against this same `backend/` directory (see the
adjacent features in the "Streaming Transcription" category). This handoff
covers only the trait and event shape; a real `DeepgramBackend` /
`AssemblyAiBackend` implements `TranscriptionBackend` the same way the fakes
here do, translating its own wire format into `TranscriptionEvent` inside
`poll_events`.

`capture::enrol::SpeakerIdentity` and this module's `SpeakerTag` currently
have the same shape (`Operator` / `Participant(String)` / `Unknown`) but are
two separate types, since `asr-live` doesn't yet depend on `capture`. Once
the crate scaffold wires that dependency, `FinalUtterance::speaker` should
be reconsidered against `capture::enrol::SpeakerIdentity` directly rather
than keeping a parallel local type.

Verified with `cargo test` and `cargo clippy` (5 passing tests, no
warnings) in a scratch crate mirroring this module tree, since the
crate-level `Cargo.toml`/`lib.rs` don't exist yet and weren't available
here to build against directly.
