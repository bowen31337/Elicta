# Deepgram on the record path — design

**Date:** 2026-08-22
**Status:** approved for planning
**Scope:** capture → service → Deepgram → transcript + diarization → debrief

---

## 1. The problem

Elicta captures audio and transcribes none of it. The gap is not one missing
client; it is a chain with three breaks in it.

**The microphone opens and the samples are discarded.** In the desktop shell
the audio thread normalises every frame to 16 kHz mono PCM and then emits an
event carrying `normalized.samples.len()` — the *count* — and drops the samples
(`apps/desktop/src-tauri/src/capture.rs`). In the browser, `browserCapture.ts`
opens the device, mutes the track on pause and releases it on stop, and never
reads a sample at all.

**Nothing holds audio in the service.** `Backend.retained_audio` is
`dict[str, str]` — a reference string, not bytes. `RecordPathTranscriptionRequest.audio_ref`
is documented as "a storage key or URI … the recording store lives outside this
package". That store does not exist.

**Nothing calls a speech vendor.** The record path falls back to two
`stub_engine`s returning the fixed transcript `"hello there"`. On the live path
the `TranscriptionBackend` trait has three implementors and all three are
scripted fakes; `core/crates/asr-live/Cargo.toml` declares no dependencies at
all, so that crate cannot open a socket. The `diarize` seam is `_no_diarizer`,
which raises.

The consequence an operator sees: the panel sits at its resting state for a
whole meeting, and the debrief stops at step 3 of architecture §7 — telling the
voices apart — producing none of the four documents.

One credential-shaped trap sits on top of this. `modules/settings/probes.py`
really does call `GET https://api.deepgram.com/v1/projects`, so the Settings
screen's **Test** button goes green against a valid Deepgram key. It validates
the credential and nothing else. A configured key currently means nothing about
whether audio ever reaches the vendor.

---

## 2. Decisions taken

| # | Decision | Rationale |
|---|---|---|
| D1 | Build the **whole chain** — capture upload, service-side hold, vendor client | A client alone would land as another component wired to nothing, which is the pattern `docs/code-quality-audit.md` exists to record |
| D2 | Deepgram fills **both** the `transcribe` and `diarize` seams | One `/v1/listen` call with `diarize=true&utterances=true` returns transcript and speaker labels together. This is what actually unblocks the debrief |
| D3 | **One engine.** `record_vendors = [deepgram]` | There is exactly one `ASR_VENDOR_API_KEY` secret and no per-vendor credential model. FR-2.6 stays unmet and *visibly* unmet — the recording screen already refuses to report an agreement it has not measured |
| D4 | **Chunked PCM upload during the meeting** | A crash loses the tail rather than the meeting; memory grows steadily instead of spiking; the audio is present the instant Stop is pressed |
| D5 | **One uploader in TypeScript, two sample sources** | Preserves the two-backend structure `useCapture` already has, and leaves one sequencing/retry implementation to get right rather than two kept in parity |

### D3 in detail

`run_record_path_transcription` already handles a single engine: `save_alignment`
is optional and documented as unnecessary "with only one engine configured".
With one engine no `SessionAlignment` is written, and the recording screen
reports that nothing was compared — which is the honest reading, and different
from "the engines agreed on nothing".

`ConnectorSettings.record_vendors` currently defaults to
`[DEEPGRAM, ASSEMBLYAI]`, which would contradict D3 the moment engines are built
from it. The default changes to `[DEEPGRAM]`, with the field's description
saying plainly that FR-2.6 wants two and one is configured.

The engine list is built **from that setting**, not hardcoded. A vendor selected
with no client behind it is refused at startup with a log line naming it —
never skipped silently, which would leave the setting claiming an engine that is
not running.

Raising this to two engines later requires growing the settings model from one
`asr_vendor_api_key` to a key per vendor: schema, store, Settings screen and the
API contract. That is separable work and deliberately out of scope here.

---

## 3. Non-goals

- **The live path.** Untouched. `asr-live` keeps its three fakes, the panel
  still sits at rest for the whole meeting, and no nudge fires. This design
  unblocks the *after the meeting* half only.
- **FR-2.6 two-engine reconciliation.** See D3.
- **A second vendor's credentials.** See D3.
- **Opus or any compression.** Raw `linear16` on the wire. Lossy encoding ahead
  of the engine the PRD calls "highest-accuracy" is a trade nobody asked for.
- **Persisting audio.** Bytes never touch disk. NFR-2.4 revises FR-1.7 to
  "retained only until the record path completes, then destroyed"; the hold is
  in service-tier memory and is destroyed by machinery that already exists.

---

## 4. Data flow

```
[Tauri]  device → NormalizingPipeline → ring buffer → drain_audio command ─┐
                                                                           ├→ audioUploader.ts
[Browser] getUserMedia → AudioWorklet → ring buffer → drain ───────────────┘        │
                                                                                    │ POST /audio-chunk
                                                                                    ▼
                                              Backend.session_audio[session] : bytearray
                                                                                    │
                                              POST /record-path-transcript          │
                                                                                    ▼
                                    deepgram transcribe seam ──→ /v1/listen ──→ BatchTranscriptionOutput
                                    deepgram diarize   seam ──→ /v1/listen ──→ DiarizationOutput
                                                                                    │
                                              both stages report done → audio destroyed,
                                                                        deletion recorded (NFR-2.4)
                                                                                    │
                                                                                    ▼
                                                            debrief §7 steps 4–8 run on text
```

---

## 5. Components

### 5.1 Desktop — sample sources

**Tauri (`src-tauri/src/capture.rs`).** The audio thread gains a buffer bounded
by the ceiling in R2 — the same ceiling applies at both ends, so neither the
shell nor the service can grow without limit — placed behind the *existing* pause check, so FR-1.3's "samples captured while paused
are dropped here, never buffered" keeps holding unchanged — the buffer append
goes after `if pause.is_paused() { continue; }`. A new `drain_audio` command
returns and clears the accumulated samples. The `capture://frame` event keeps
carrying counts only; the PCM travels by explicit drain, not by event, so a slow
frontend cannot flood the IPC channel.

**Browser (`browserCapture.ts`).** An `AudioWorklet` at 16 kHz mono writes Float32
frames into an equivalent ring, converted to `linear16` on drain. `MediaRecorder`
is not used: it produces a compressed container, not raw PCM.

Both expose the same shape, so `useCapture` chooses a sample source exactly the
way it already chooses a capture backend.

### 5.2 Desktop — the uploader

One new module, `features/capture/audioUploader.ts`, written as plain functions
over an injectable `fetch` in the style of `prepActions.ts`, so it is testable
without a network.

- Drains on a timer, ships whole chunks, never partial ones.
- Each chunk carries a monotonic `sequence` starting at 0.
- A failed chunk is retried with backoff **before** the next is sent; order is
  preserved rather than repaired server-side.
- Chunks are dropped only when the buffer ceiling is hit (§9), and that is
  surfaced to the operator, never silent.

### 5.3 Service — the audio hold

```python
# Backend
session_audio: dict[str, bytearray] = field(default_factory=dict)
```

Deliberately **not** durable. `test_only_the_continuity_fields_are_made_durable`
gains an assertion that `session_audio` is not a `DurableMapping`, so FR-1.7 is
enforced by a test rather than by intention — the same way that test already
pins `transcript_cleanings` as rebuilt-not-stored.

New route, mounted in `composition.py` like every other:

```
POST /api/sessions/{session_id}/audio-chunk
  { "sequence": int >= 0, "pcm": <base64 linear16 16kHz mono> }
  → 202 { "received_bytes": int, "next_sequence": int }
  → 409 when sequence != next expected — the response names the gap
```

A gap is refused rather than concatenated across. Silently joining two sides of
a dropped chunk produces a transcript with a seam nobody can see, which is worse
than a refusal the uploader can retry.

**`audio_ref` is defined here as `f"session:{session_id}"`.** It has never had a
concrete value — the schema calls it "a storage key or URI" from a store that
does not exist. Now it names the in-memory hold, and `read_audio` resolves it
back to bytes. `session_id` is the meeting id: the record path keys everything by
the meeting and calls it a session, which is the mismatch that once handed both
engines an empty keyterm list.

The first accepted chunk sets `retained_audio[session_id]` to that ref, so
`on_audio_retained`, `is_ready_for_audio_destruction` and `delete_audio` all keep
working untouched. `delete_audio` additionally clears `session_audio[session_id]`.

### 5.4 Service — the Deepgram client

New module `app/orchestration/deepgram_engines.py`. Two factories, each
returning a callable shaped exactly like the seam it fills:

```python
def deepgram_record_engine(read_audio, credentials, *, model="nova-3", name="deepgram")
    -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]

def deepgram_diarizer(read_audio, credentials, *, model="nova-3", name="deepgram")
    -> Callable[[str, str], Awaitable[DiarizationOutput]]
```

`read_audio(session_id) -> bytes` is injected rather than imported, so the
client never reaches for `Backend` — the same seam discipline as
`orchestration/engines.py`.

**The request.**

```
POST https://api.deepgram.com/v1/listen
  ?model=nova-3
  &diarize=true
  &utterances=true
  &smart_format=true
  &encoding=linear16&sample_rate=16000&channels=1
  &mip_opt_out=true
  &keyterm=<term>            (repeated per term, phrases percent-encoded)
Authorization: Token <asr_vendor_api_key>
Content-Type: application/octet-stream
body: raw linear16 PCM
```

- `keyterm` is repeated once per term and is Nova-3-only; multi-word phrases are
  percent-encoded. This is the path the engagement vocabulary travels, which the
  handbook calls the single most effective thing an operator can do for accuracy.
- `mip_opt_out=true` is Deepgram's zero-retention parameter, already named in
  `core/egress/retention.py`, and matches the `disable_vendor_retention` setting.
- Credentials are read **per call** from the settings store, matching
  `SettingsBackedClient`, so a key changed in the UI takes effect without a
  restart.

**Response mapping.**

| Deepgram | Elicta |
|---|---|
| `results.utterances[].{start,end,transcript,speaker}` | `TranscriptSegment{start_seconds,end_seconds,text,speaker}` |
| `results.channels[0].alternatives[0].transcript` | `BatchTranscriptionOutput.text` |
| consecutive `utterances[]` merged by equal `speaker` | `SpeakerTurn{start_seconds,end_seconds,speaker_tag}` |

The diarizer returns `DiarizationOutput{engine, turns}` — **turns, not
utterances**. `run_diarization` builds `Utterance`s itself from the record-path
spans and calls `tag_span_speaker(span, output.turns)`, so returning utterances
directly would bypass the tagging rule that guarantees `speaker_tag` is never
null.

### 5.4a What starts the transcription

Nothing calls `POST /record-path-transcript` today; the endpoint exists and has
no caller anywhere in `apps/desktop`. The chain needs a trigger, and it is the
operator pressing **Stop**.

On stop, `useCapture` flushes any remaining buffered samples, waits for the last
chunk to be acknowledged, then posts
`/api/sessions/{meeting_id}/record-path-transcript` with
`{"audio_ref": "session:{meeting_id}"}`. Transcription is therefore explicitly
triggered rather than inferred from the chunk stream going quiet — a pause, a
flaky network and a finished meeting all look identical from the server side, and
starting a transcription on a mid-meeting lull would transcribe half a session
and then destroy the audio.

The flush is what makes Stop honest: the screen keeps saying it is finishing
until the last chunk lands, rather than reporting a completed recording whose
tail never arrived.

### 5.5 Service — wiring

`main.py` gains both seams and passes them down:

```python
debrief_engines, compiler_engines = engines_from_settings(store, diarize=deepgram_diarizer(...))
app = build_app(backend, ..., record_path_engines=[deepgram_record_engine(...)])
```

Both are wrapped with `_audit_seam`, so every call writes an egress row by
construction — the same mechanism the compiler seams use. The unused
`EgressTransport` / `PinningEgressTransport` / `RetentionEnforcingEgressTransport`
stack is deliberately **not** adopted here: it is synchronous, has no concrete
implementation anywhere in the tree, and adopting it would mean writing one and
adapting the chokepoint. `audited()` is the mechanism actually in use. Retention
is set directly on the request as `mip_opt_out=true`, which is what that stack
would have set anyway.

---

## 6. Error handling

Every failure is recorded and named; none is guessed past.

- **A Deepgram call raises** → `run_record_path_transcription` persists a
  `FAILED` `RecordPathTranscript` carrying the error, and `run_diarization`
  persists a `FAILED` `SessionDiarization`. Both already do this; the client
  only has to raise honestly rather than return an empty result.
- **No audio held for the session** → the seam raises before any request is
  made. Transcribing silence would produce an empty transcript that reads like a
  meeting where nobody spoke.
- **504 from Deepgram** (processing-time ceiling, §9) → surfaced as its own
  cause, not folded in with a network failure. The remedies differ.
- **A chunk arrives out of sequence** → 409 naming the expected sequence. The
  uploader retries; the service never invents the missing audio.
- **Unconfigured credential** → `EngineNotConfiguredError`, which the existing
  handler turns into a 503 naming the setting that would fix it.

---

## 7. Testing

TDD throughout: every behaviour below gets a failing test first.

**Service**
- A chunk appends; a gap is refused with the expected sequence named.
- `session_audio` is not a `DurableMapping` (FR-1.7 as a test).
- Deepgram response → `BatchTranscriptionOutput` and → `DiarizationOutput`,
  against **recorded fixtures**. No test makes a live call.
- Consecutive same-speaker utterances merge into one `SpeakerTurn`.
- Keyterms from the engagement vocabulary appear on the request, repeated.
- `mip_opt_out=true` is on every request.
- One egress row per vendor call, success or failure.
- Audio is destroyed once both stages report done, and the deletion recorded.

**Desktop**
- Uploader sequencing, ordered retry, and behaviour at the buffer ceiling.
- Worklet output is `linear16` at 16 kHz mono.
- Samples captured while paused never reach the buffer (FR-1.3 regression).
- Both sample sources produce the same shape.

**Live verification**, as an explicit final step against the real key: run a
short meeting end to end and confirm a real transcript, real speaker tags, and
the four debrief documents.

---

## 8. Definition of done

1. A meeting recorded in the browser at `https://<host>:1420` produces a real
   `RecordPathTranscript` from Deepgram.
2. Its `SessionDiarization` carries real speaker tags.
3. The debrief runs past step 3 and produces the four documents with citations.
4. The audio is destroyed afterwards and the deletion is in the audit trail.
5. `GET /api/audit/egress` shows one row per vendor call.
6. Full suites green: service, API integration, desktop, ruff, clippy.
7. Journeys 3/6/7 status tables and the handbook chapter they feed are updated
   to say what now works — including that the live path still does not.

---

## 9. Risks

**R1 — Deepgram's processing-time ceiling.** The docs are explicit: *"Requests
exceeding 10 minutes for Nova, Base, and Enhanced models … will result in a 504
Gateway Timeout error."* That is processing time, not audio duration, and
Deepgram processes faster than real time — but a 90-minute meeting is a
plausible way to hit it. The documented escape is `callback`, which needs either
a publicly reachable URL or a polling arrangement, and is a materially different
integration.

*Resolution:* a spike **before** implementation — submit a long file against the
real key and find where the wall is. If a realistic meeting exceeds it, the
callback flow becomes part of this design and the spec is revised before code is
written. This is the one item that could change the shape of the work.

**R2 — Unbounded memory.** ~115 MB per hour per session, in service RAM, with no
ceiling. Two sessions and a long meeting could exhaust a laptop. *Mitigation:* a
configurable ceiling that stops accepting chunks and says so on the Capture
screen. A recording that stops with an explanation is recoverable; a service
killed by the OOM killer mid-meeting is not.

**R3 — IPC volume in the Tauri path.** ~32 KB/s of PCM crossing the Tauri
boundary as base64. Expected to be immaterial, unverified. *Mitigation:* measured
during implementation; if it bites, the drain interval lengthens before anything
architectural changes.

**R4 — The vocabulary handshake is unproven against a real vendor.** Keyterms
have only ever been passed to stubs. *Mitigation:* covered by the live
verification step, asserting a known product name transcribes correctly.

**R5 — Browser and shell divergence.** Two sample sources can drift.
*Mitigation:* the shared-shape test in §7, and `parity.yml` already exists for
this class of problem.
