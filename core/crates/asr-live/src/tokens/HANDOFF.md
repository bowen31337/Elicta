# tokens module — handoff

Implements PRD FR-2.10 (one websocket per participant stream when managed
capture provides separated audio). Self-contained under this directory;
deliberately does not touch `core/crates/asr-live/Cargo.toml` or
`core/crates/asr-live/src/lib.rs`, since those are owned by the crate
scaffold and (per this task's declared footprint) shared with sibling
plugin submodules of the asr-live crate.

Neither the crate manifest nor `src/lib.rs` existed yet in this worktree at
the time this module was written, so this mirrors the pattern already used
by `core/crates/language/src/numerals` for the same situation.

## Wiring needed (one line, in the shared `lib.rs`)

Whoever owns `core/crates/asr-live/src/lib.rs` needs to add:

```rust
pub mod tokens;
```

This module has no dependency on any other asr-live submodule and no
external crate dependencies (pure `std`), so no `Cargo.toml` changes are
required for it specifically.

## What's here

- `mod.rs` — public API re-exports and the `ParticipantId` type alias
  (mirrors `capture::enrol::stream_identity::ParticipantId`; not imported
  from that crate to avoid taking on a cross-crate dependency decision that
  belongs to the scaffold owner).
- `event.rs` — `TokenEvent`, one ASR token tagged with the participant it
  came from.
- `socket.rs` — `TokenSocket` / `TokenSocketFactory` traits abstracting the
  actual websocket connection to the ASR vendor, so the dispatch logic
  below is testable without a real socket. The asr-live crate's real
  transport (whatever websocket client it settles on) should implement
  `TokenSocket`; this module never constructs a socket itself except via a
  supplied factory.
- `registry.rs` — `ParticipantTokenStreams<F>`, which opens exactly one
  socket per participant (never more, never reused across participants)
  and routes each participant's separated audio frames to its own socket.
  This is the piece that makes "each participant emits its own event
  stream" true rather than just documented.

## Suggested integration point

Whatever in asr-live currently receives per-participant separated audio
frames from `capture` (per `capture::enrol::stream_identity::IdentifiedStream`)
should own one `ParticipantTokenStreams<RealSocketFactory>` for the
meeting and call `dispatch(participant_id, samples)` per frame, `end(id)`
when a participant leaves. `active_stream_count()` / `is_active()` are
exposed for whatever surfaces "N participants transcribing" in
telemetry/UI.

Verified with `cargo test` (4 passing tests) in a scratch crate mirroring
this module tree, since `core/crates/asr-live/Cargo.toml` /
`src/lib.rs` don't exist in this worktree yet.
