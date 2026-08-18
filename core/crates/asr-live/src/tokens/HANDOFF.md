# tokens module — handoff

Implements PRD FR-2.10 (one websocket per participant stream when managed
capture provides separated audio) and, on `TokenEvent`, PRD FR-2.3 /
NFR-5.6 (every token — partial or final — carries a populated
`confidence: f32`, since that's what the input-span gate reads to decide
whether a span is trustworthy). Also implements the requirement that every
finalised utterance is persisted to the append-only utterances table before
any consumer reads it. Self-contained under this directory.

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

## Rejecting utterance-level-only backends at startup (PRD FR-2.3, NFR-5.6)

A vendor that only ever produces one confidence score per whole utterance
can't back per-token confidence no matter how its `TokenSocket` is wired,
since there's no per-word score to carry through in the first place.
`TokenSocketFactory::confidence_granularity` makes a vendor declare which
shape it produces, and `ParticipantTokenStreams::new` calls
`socket::validate_backend` against that declaration before constructing
anything — an `UtteranceLevel` vendor makes `new` return
`Err(BackendRejected(..))` with a message naming both what the vendor
reported and what the input-span gate requires, instead of the crate
quietly accepting a vendor it can never gate correctly. See
`registry.rs`'s `a_backend_reporting_only_utterance_level_confidence_is_rejected_at_startup`
test. A real `TokenSocketFactory` implementation must return
`ConfidenceGranularity::PerToken` truthfully — there is no default impl to
fall back on, precisely so this can't be satisfied by omission.

## Persisting every finalised utterance before any consumer reads it

`ParticipantTokenStreams::dispatch` is the one place a finalized
`TokenEvent` is produced and the one place a caller can observe one.
Before `dispatch` returns, it wraps every event with `is_final == true`
into a `FinalizedUtterance` (`utterance_table.rs`) and appends it to the
`UtteranceTable` the registry owns — a plain synchronous call, so there is
no window where the `Vec<TokenEvent>` handed back to the caller contains a
finalized event the table doesn't already have. `ParticipantTokenStreams::table()`
exposes the table for read-back, and by construction it only ever shows
rows that were already durable before any caller — the immediate
`dispatch` return value or a later read of `table()` — could have observed
them. `FinalizedUtterance::from_token` is the only constructor and rejects
a partial with `NotFinal`, so a table implementation can never receive a
row that wasn't actually finalized. See `registry.rs`'s
`a_finalized_event_is_recorded_in_the_utterances_table_by_the_time_dispatch_returns`
and `partial_events_are_never_written_to_the_utterances_table` tests.

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
- `utterance_table.rs` — `FinalizedUtterance` (a `TokenEvent` proven final)
  and `UtteranceTable`, the append-only trait `dispatch` persists every
  finalized event to before returning it. `InMemoryUtteranceTable` is the
  exported in-memory default (mirrors `backend::fake`'s "exported, not
  test-only" pattern) — a real durable table (e.g. backed by
  `crypto::sqlite`, the way `bank::store::BankStore` is) can implement the
  same trait later without this module's persist-before-return guarantee
  changing.
- `registry.rs` — `ParticipantTokenStreams<F, T>`, which opens exactly one
  socket per participant (never more, never reused across participants),
  routes each participant's separated audio frames to its own socket, and
  owns the `T: UtteranceTable` every finalized event is persisted to before
  `dispatch` returns. This is the piece that makes "each participant emits
  its own event stream" and "every finalised utterance is durably recorded
  before any consumer reads it" both true rather than just documented.

## Suggested integration point

Whatever in asr-live currently receives per-participant separated audio
frames from `capture` (per `capture::enrol::stream_identity::IdentifiedStream`)
should own one `ParticipantTokenStreams<RealSocketFactory, RealUtteranceTable>`
for the meeting and call `dispatch(participant_id, samples)` per frame,
`end(id)` when a participant leaves. `active_stream_count()` / `is_active()`
are exposed for whatever surfaces "N participants transcribing" in
telemetry/UI. Until a real durable `UtteranceTable` exists, constructing
with `InMemoryUtteranceTable::new()` is a working default; swapping in a
durable implementation (SQLite-backed, matching `bank::store::BankStore`'s
shape) is a decision for whoever owns this crate's dependency list, since
this crate currently has none (`backend/HANDOFF.md`: "every crate in this
workspace is std-only so far").

## Deliberately out of scope here

- A real durable (on-disk / networked) `UtteranceTable` implementation:
  this crate has no external dependencies today, so `InMemoryUtteranceTable`
  is what `dispatch`'s persist-before-return guarantee is proven against.
  The guarantee itself (append happens inside `dispatch`, before its
  return) does not change when a durable implementation is swapped in.
- Reading the utterances table from outside the `ParticipantTokenStreams`
  that wrote to it (e.g. a separate process or a UI querying persisted
  transcript history): `UtteranceTable::append` and `table()` are exposed
  for whoever wires that read path, but this module doesn't itself expose
  one over any transport.

Verified with `cargo test` and `cargo clippy --all-targets` against the
real crate (49 passing tests across the whole `asr-live` crate, no
warnings).
