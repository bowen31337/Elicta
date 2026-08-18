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
    AudioEncoding, AudioFramer, AudioSegmentRef, BackendError, CaptureStartBackend,
    ConnectionEvent, EndpointResolutionError, EngagementId, EngagementRegionRegistry,
    FinalUtterance, FrameDurationError, FramedBackend, InterimHypothesis, KeepaliveBackend,
    KEEPALIVE_INTERVAL, Keyterm, LanguageTag, LINEAR16_16KHZ_MONO, MAX_FRAME_MS, MIN_FRAME_MS,
    Region, RegionPinError, RegionPinnedBackend, RegionalConnectError, RegionalEndpointResolver,
    SpeakerTag, StreamId, Token, TranscriptionBackend, TranscriptionEvent, UtteranceId,
    VendorRegionEndpoints,
};
```

## What's here

- `encoding.rs` — the audio encoding declared on every vendor connection
  (architecture §14.1 point 3, "Do not double-compress": conference audio
  has already been through a lossy codec once, so send `encoding=linear16`
  at `sample_rate=16000` rather than re-encoding to Opus). `AudioEncoding`
  is a plain value (`codec`, `sample_rate_hz`, `channels`); the crate
  exposes exactly one instance of it, `LINEAR16_16KHZ_MONO`, and no
  lossy-codec variant — the "unless bandwidth genuinely forbids it"
  exception architecture §14.1 allows is a deployment-time call, not
  something this crate models as a fallback default a vendor backend could
  reach for silently. `AudioEncoding::as_query_string` renders the
  parameter names Deepgram's and AssemblyAI's streaming endpoints both
  accept directly on the connection URL, and
  `AudioEncoding::apply_to_endpoint` appends that query string onto a
  resolved endpoint (correctly joining with `?` or `&` depending on
  whether the endpoint already carries one) — composed with
  `RegionalEndpointResolver::resolve` from `region.rs`, a real vendor
  backend's `connect` closure gets the one URL that is both regionally
  pinned and non-lossy, without a call site needing to remember to append
  the encoding by hand.
- `event.rs` — the value types architecture §3.2 specifies verbatim:
  `InterimHypothesis`, `FinalUtterance`, `Token`, plus the `TranscriptionEvent`
  enum that unions them into the one shape every backend emits. `StreamId`,
  `UtteranceId`, and `LanguageTag` are plain `String` aliases; `SpeakerTag`
  and `AudioSegmentRef` are minimal local types.
- `transcription_backend.rs` — the `TranscriptionBackend` trait itself
  (`start_stream` / `send_audio` / `poll_events`, synchronous push/drain, no
  `async`) and `BackendError`. `start_stream` is the keyterm handshake (PRD
  FR-2.9): every implementation must send the engagement vocabulary passed
  to it as keyterm prompting before accepting any audio for that
  `stream_id`, and must reject a `send_audio` call for a stream that hasn't
  been started yet — the same vocabulary the record path sends via
  `GetEngagementVocabulary` in `app/modules/asr-record`, injected here on
  the live path's handshake instead.
- `fake.rs` — two scripted, non-networked test-double vendors
  (`ImmutablePartialFakeBackend`, mimicking AssemblyAI-style immutable
  partials, and `RevisablePartialFakeBackend`, mimicking Deepgram-style
  revised partials) used to prove the trait's core property: both emit the
  same `TranscriptionEvent` shape and can be driven by one function written
  generically over `impl TranscriptionBackend`, standing in for how the
  trigger gate will consume either vendor without knowing which one it is.
  Both record the keyterms handed to `start_stream` (inspectable via
  `keyterms_sent`) and reject `send_audio` before that handshake has
  happened. These are exported, not test-only, so whoever wires the trigger
  gate can develop against them before a real vendor connection exists.
- `connection.rs` — `CaptureStartBackend`/`ConnectionEvent` (architecture
  §14.2, "open the socket before the meeting, not at first speech").
  `CaptureStartBackend::open` calls its `connect` closure immediately —
  meant to be invoked once per capture session, before the first
  participant has spoken — and queues a `ConnectionEvent::Ready` a caller
  drains via `poll_connection_events`, separately from
  `TranscriptionBackend::poll_events`, so a connection-lifecycle signal is
  never mistaken for transcript content. Because `Ready` is queued at
  `open` and every `start_stream`/`send_audio` call happens strictly after
  a caller holds the constructed `CaptureStartBackend`, draining
  `poll_connection_events` before pushing any audio makes "the connection
  emitted a ready event before the first utterance" true by construction,
  not by call-site convention. Generalises the "open eagerly" half of what
  `RegionPinnedBackend::open` already does (see below) to any backend,
  region-pinned or not, and adds the `Ready` signal region pinning doesn't
  need for its own purpose.
- `region.rs` — per-engagement ASR vendor region pinning (architecture
  §14.2 "Pin the region", PRD NFR-2.2). `EngagementRegionRegistry` pins an
  `EngagementId` to a `Region` once and rejects a mid-engagement repin to a
  *different* region; `VendorRegionEndpoints` maps a vendor's known regions
  to their endpoint URLs; `RegionalEndpointResolver` composes the two to
  resolve the one endpoint an engagement's requests must reach.
  `RegionPinnedBackend<B>` wraps any `TranscriptionBackend` and resolves
  that endpoint exactly once, in `open`, at the same moment the connection
  itself is opened (architecture §14.2's "open the socket before the
  meeting") — every `start_stream` / `send_audio` / `poll_events` call
  afterwards delegates to that same bound `inner` connection, so "every
  request sends to the pinned regional endpoint" holds structurally rather
  than by call-site convention. `open` never calls its `connect` closure at
  all if the engagement has no region pinned or the pinned region has no
  known vendor endpoint, so a connection is never opened against the wrong
  (or no) endpoint.
- `framing.rs` — re-chunks outgoing audio into fixed-size vendor frames of
  between `MIN_FRAME_MS` (20ms) and `MAX_FRAME_MS` (50ms) at 16kHz mono
  (architecture §14.2: balances quantisation delay against per-message
  overhead). `AudioFramer` buffers arbitrary-sized pushes and drains
  full-length frames in arrival order, leaving any short remainder
  buffered until `flush` (or the next `push`) completes it — a frame is
  never sent undersized. `FramedBackend<B>` wraps any `TranscriptionBackend`
  and applies this transparently: every `send_audio` call reaching the
  wrapped `inner` backend carries exactly `duration_ms` of audio, keyed per
  `stream_id` so two streams' remainders never bleed into each other's
  frames. Constructing with a duration outside `[MIN_FRAME_MS,
  MAX_FRAME_MS]` fails immediately rather than silently clamping.
- `keepalive.rs` — holds the connection open for the duration of the
  meeting via fixed-interval keepalive frames (architecture §14.2, "held
  with keepalives rather than reopened per utterance"). Adds
  `TranscriptionBackend::send_keepalive` to the trait itself — what a
  keepalive frame looks like on the wire is vendor-defined, the same reason
  `start_stream`/`send_audio` are trait methods rather than something a
  wrapper could synthesize generically — defaulted to a no-op so a
  scripted/non-networked implementation (this module's own fakes, or
  `stream::fake::PrematureEndpointFakeBackend`, which implements this trait
  but lives outside this directory) isn't forced to implement a method it
  has no real connection to exercise; a real vendor backend overrides it.
  `KeepaliveBackend<B>` supplies the vendor-agnostic scheduling half:
  `tick(elapsed)` advances an idle clock and calls `send_keepalive` once per
  full `interval` (a `tick` spanning several intervals sends one keepalive
  per interval, never fewer). `KEEPALIVE_INTERVAL` (5s) is the fixed cadence
  architecture §14.2 calls for; `KeepaliveBackend::with_default_interval`
  uses it directly. Any `start_stream` or `send_audio` call resets the idle
  clock, since real traffic on the connection already keeps it alive
  without help. Driven by
  an explicit `tick` call rather than a background timer, matching every
  other wrapper in this module — this crate is std-only and
  non-networked, so whatever drives real wall time (a timer thread, an
  event loop tick) lives outside this crate.

## Deliberately out of scope here

Everything about how a *real* vendor connection is driven once open beyond
keepalives — reconnect-on-drop chief among it — is separately scoped work
against this same `backend/` directory (see the adjacent features in the
"Streaming Transcription" category). This handoff covers the trait, event
shape, the keyterm handshake, region pinning, audio framing, the
capture-start `Ready` signal, and fixed-interval keepalives; a real
`DeepgramBackend` /
`AssemblyAiBackend` implements `TranscriptionBackend` the same way the
fakes here do, translating its own wire format into `TranscriptionEvent`
inside `poll_events` and sending `start_stream`'s keyterms as that
vendor's own keyterm-prompting mechanism on connection open — and is
opened via `RegionPinnedBackend::open` (itself invoked from inside a
`CaptureStartBackend::open` closure, so the eager-open and `Ready` signal
both happen at capture start) so its actual websocket connect target is
the resolved regional endpoint rather than a hardcoded default host, then
wrapped in `FramedBackend` so every `send_audio` call it receives already
carries a vendor-sized 20-50ms frame regardless of how the capture
pipeline chunked the audio upstream, and finally wrapped in
`KeepaliveBackend` so it receives a `send_keepalive` call every
`KEEPALIVE_INTERVAL` of silence — whoever wires the real event loop still
needs to call `KeepaliveBackend::tick` on some periodic cadence (a timer
thread, an event loop's own tick), since that's the one piece of real wall
time this std-only crate can't produce itself.

- `CaptureStartBackend` does not itself enforce that a caller drains
  `poll_connection_events` before calling `start_stream` — like
  `FramedBackend`'s per-stream framer state, it makes the correct ordering
  the easy, structural default (there's nothing to observe from
  `poll_connection_events` if a caller never calls `open` first), but a
  caller that calls `start_stream` without ever draining `Ready` still
  gets correct transcription behaviour, just without observing the signal
  it was offered.

`capture::enrol::SpeakerIdentity` and this module's `SpeakerTag` currently
have the same shape (`Operator` / `Participant(String)` / `Unknown`) but are
two separate types, since `asr-live` doesn't yet depend on `capture`. Once
the crate scaffold wires that dependency, `FinalUtterance::speaker` should
be reconsidered against `capture::enrol::SpeakerIdentity` directly rather
than keeping a parallel local type.

Verified with `cargo test -p asr-live` and `cargo clippy -p asr-live
--all-targets` against the real crate (40 passing tests in this module, no
warnings).
