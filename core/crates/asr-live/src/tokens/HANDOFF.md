# tokens module — handoff

Implements PRD FR-2.10 (one websocket per participant stream when managed
capture provides separated audio) and, on `TokenEvent`, PRD FR-2.3 /
NFR-5.6 (every token — partial or final — carries a populated
`confidence: f32`, since that's what the input-span gate reads to decide
whether a span is trustworthy). Self-contained under this directory.

The crate scaffold (`Cargo.toml`, `src/lib.rs`) now exists and already
wires this module in via `pub mod tokens;` — the wiring note that used to
live here is done.

## Confidence on every token (PRD FR-2.3, NFR-5.6)

`TokenEvent::confidence` has no default: both `TokenEvent::partial` and
`TokenEvent::finalized` require a caller to pass one, so a `TokenSocket`
implementation cannot construct a token that skips it. This mirrors the
same requirement already enforced independently on `backend::Token` (see
`core/crates/asr-live/src/backend/event.rs`) for the finalized-utterance
side of this crate — that module's `Token` is a different type for a
different event shape (batched tokens inside a `FinalUtterance`), not this
module's live per-word `TokenEvent`, so both need their own populated
confidence field rather than one being derivable from the other.

A real `TokenSocket` translating vendor wire frames into `TokenEvent`s must
carry the vendor's own per-word confidence score through rather than
inventing a placeholder value — see `registry.rs`'s
`every_dispatched_token_carries_a_confidence_value` test for the shape that
invariant takes at the `ParticipantTokenStreams::dispatch` boundary.

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

Verified with `cargo test` and `cargo clippy --all-targets` against the
real crate (11 passing tests across the whole `asr-live` crate, no
warnings).
