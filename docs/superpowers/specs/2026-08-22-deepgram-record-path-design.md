# Two speech vendors on the record path — design

**Date:** 2026-08-22
**Status:** approved for planning; R1 closed by measurement (§9)
**Revision:** two vendors, after the R1 spike found a working Deepgram
credential and a working AssemblyAI one. D3 reversed.
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
| D2 | A vendor call fills **both** the `transcribe` and `diarize` seams | One Deepgram `/v1/listen` with `diarize=true&utterances=true` returns transcript and speaker labels together. This is what actually unblocks the debrief; D3a settles which vendor supplies the speaker map |
| D3 | **Two engines**, Deepgram and AssemblyAI, with a credential each | Both keys exist and both were validated. FR-2.6 and T3 are met rather than deferred: the enum's own docstring says these two are a usable pair *because* their lineages are independent, and reconciliation is worthless between engines that fail the same way |
| D3a | **Only Deepgram diarizes** | `run_diarization` takes exactly one `diarize`. Two engines would produce two conflicting speaker maps for the same audio and nothing arbitrates. Deepgram's utterance/speaker shape is observed (§9 R1); AssemblyAI's is not |
| D4 | **Chunked PCM upload during the meeting** | A crash loses the tail rather than the meeting; memory grows steadily instead of spiking; the audio is present the instant Stop is pressed |
| D5 | **One uploader in TypeScript, two sample sources** | Preserves the two-backend structure `useCapture` already has, and leaves one sequencing/retry implementation to get right rather than two kept in parity |

### D3 in detail — the credential model

`ConnectorSettings.record_vendors` already defaults to
`[DEEPGRAM, ASSEMBLYAI]`, so the setting has always described two engines. What
was missing is somewhere to put the second key.

Today there is one `SecretKey.ASR_VENDOR_API_KEY`, and its **Test** button
probes `connectors.live_vendor` — not the record vendors. One key is therefore
silently assumed to authenticate whichever vendor happens to be on the live
path, which is incoherent the moment two record vendors need two keys. It is
also how a dead key came to read as "configured": it was only ever checked
against one vendor's endpoint, and only when somebody pressed the button.

The change:

- `SecretKey` gains `DEEPGRAM_API_KEY` and `ASSEMBLYAI_API_KEY`.
- `_SECRET_ENV` gains `ELICTA_DEEPGRAM_API_KEY` and `ELICTA_ASSEMBLYAI_API_KEY`
  as the headless fallbacks. Both are added to `.env.example`, which is the
  source of truth for env-var names, and to the RUNBOOK table — which currently
  says outright that ASR credentials are *not* in it.
- Each key's **Test** probes *its own* vendor via `probe_for_vendor`, rather
  than whichever vendor `live_vendor` names. A per-vendor key tested against
  another vendor's endpoint is a meaningless green tick.
- The engine list is built **from `record_vendors`**, not hardcoded. A vendor
  selected with no credential is refused at startup with a log line naming it —
  never skipped silently, which would leave the setting claiming an engine that
  is not running.

**Migration.** The existing `asr_vendor_api_key` is dead — 40 characters,
rejected 401 by both vendors. It is neither silently dropped nor silently
reused as one vendor's key: both are guesses about a credential nobody can
verify. It reads as *not configured* and the value is discarded, which is
exactly the behaviour an undecryptable secret already has. The operator
re-enters each key beside the vendor it belongs to, which is the first time the
screen has been able to ask that question.

`ASR_VENDOR_API_KEY` itself stays, for the live path, unchanged. This design
does not touch the live path and must not orphan its credential.

---

## 3. Non-goals

- **The live path.** Untouched. `asr-live` keeps its three fakes, the panel
  still sits at rest for the whole meeting, and no nudge fires. This design
  unblocks the *after the meeting* half only. `ASR_VENDOR_API_KEY` keeps
  serving it.
- **Diarizing with both engines.** See D3a — one speaker map, from Deepgram.
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
                    deepgram   transcribe ──→ /v1/listen ─────────────→ BatchTranscriptionOutput ─┐
                    assemblyai transcribe ──→ upload/poll/delete ────→ BatchTranscriptionOutput ─┤
                                                                                    │            │
                                                                    SessionAlignment ←───────────┘
                                                                     (divergence, FR-2.6/2.8)
                                    deepgram   diarize    ──→ /v1/listen ─────────→ DiarizationOutput
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

### 5.4 Service — the vendor clients

Two modules, `app/orchestration/deepgram_engines.py` and
`app/orchestration/assemblyai_engines.py`. Both produce callables shaped exactly
like the seam they fill, so `run_record_path_transcription` cannot tell them
apart — the whole point of running two engines is that the code treats them
identically and only their *output* differs.

`read_audio(session_id) -> bytes` is injected into both rather than imported, so
neither client reaches for `Backend`, matching the seam discipline in
`orchestration/engines.py`.

#### 5.4a Deepgram — one blocking request

Measured, not assumed: 90 minutes of speech returns in 71 seconds (§9 R1).

```python
def deepgram_record_engine(read_audio, credentials, *, model="nova-3", name="deepgram")
    -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]

def deepgram_diarizer(read_audio, credentials, *, model="nova-3", name="deepgram")
    -> Callable[[str, str], Awaitable[DiarizationOutput]]
```

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
- `mip_opt_out` is Deepgram's zero-retention parameter, already named in
  `core/egress/retention.py`. It carries the `disable_vendor_retention` setting
  rather than a constant: that switch is on the Settings screen, and one an
  operator can toggle while the request ignores it is worse than one not
  offered. It defaults to on, so the opt-out is what an untouched deployment
  sends. `keyterm_prompting` governs the vocabulary on the same terms — off,
  no `keyterm` is sent.
- Credentials are read **per call** from the settings store, matching
  `SettingsBackedClient`, so a key changed in the UI takes effect without a
  restart.
- **The client timeout is explicit and generous.** A 90-minute meeting holds the
  connection open for over a minute; `httpx`'s default would abort a
  transcription that was proceeding perfectly well. This is a real defect the
  spike would have shipped had it not been measured.

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

The mapping above is **observed**, not inferred. A 90-minute run returned 1647
utterances whose keys are
`['channel','confidence','end','id','speaker','start','transcript','words']`.

#### 5.4b AssemblyAI — upload, poll, delete

A different shape, and the difference is not cosmetic: audio is uploaded to the
vendor's storage first, then referenced.

```
POST   /v2/upload                  raw PCM body        → { upload_url }
POST   /v2/transcript              { audio_url, speaker_labels: true,
                                     word_boost: [...] }   → { id }
GET    /v2/transcript/{id}         poll until status ∈ {completed, error}
DELETE /v2/transcript/{id}         remove the vendor-side copy
```

- Limits are far outside a meeting: **10 hours of audio, 5 GB** (2.2 GB via
  `/v2/upload`). A 90-minute meeting is ~173 MB. There is no synchronous
  processing ceiling to hit, because it is a polling API by construction.
- `word_boost` carries the engagement vocabulary, the counterpart to Deepgram's
  `keyterm`, and is governed by the same `keyterm_prompting` setting.
  `disable_vendor_retention` has no counterpart here: this API takes no
  retention parameter, and the mandatory `DELETE` below is the whole of this
  vendor's retention control.
- **The `DELETE` is mandatory, not optional.** It is the only reason this
  vendor's flow is acceptable under the audio promise: Deepgram takes the bytes
  in the transcription request and keeps nothing, whereas AssemblyAI stores a
  copy until it is removed. One path cannot honour it: an upload that never
  became a transcript has no handle to delete it by, because
  `DELETE /v2/transcript/{id}` removes the audio *through* its transcript and
  the API exposes no other deletion. That copy is therefore made discoverable
  instead — logged at ERROR and named, with its URL, in the failure the
  recording screen shows — and the vendor's own retention removes it within 48
  hours. A verified deletion is a stronger claim than a
  retention flag — it is the same standard NFR-2.4 already holds our own audio
  to, *"the deletion is itself recorded, so the destruction can be shown rather
  than asserted"* — but only if it actually runs. It is recorded in the egress
  log like any other call, and a failed delete is surfaced, never swallowed.
- Polling backs off and has a ceiling. A transcript stuck in `processing`
  forever must fail the stage with that reason rather than hang the debrief.

**This changes what you can tell a client**, and the consent copy has to match:
one vendor is sent the audio, the other is sent *and stores* it until we delete
it. That is a difference an operator should not discover from a support ticket.

### 5.5 What starts the transcription

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

### 5.6 Service — wiring

`main.py` builds the engine list from `record_vendors`, one client per selected
vendor, each with its own credential; the diarizer is Deepgram's alone (D3a):

```python
engines = build_record_engines(store, read_audio)   # from connectors.record_vendors
debrief_engines, compiler_engines = engines_from_settings(
    store, diarize=deepgram_diarizer(read_audio, store)
)
app = build_app(backend, ..., record_path_engines=engines)
```

With two engines `save_alignment` receives its two `COMPLETE` transcripts and
writes a real `SessionAlignment`, so the divergence screen shows measured
disagreement instead of reporting that nothing was compared.

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
- **One engine fails, the other does not** → already handled and load-bearing:
  each engine's outcome persists independently, and that independence is the
  reason two are run. No alignment is written from one transcript.
- **A 504 from Deepgram** (processing ceiling) → its own cause, not folded in
  with a network failure. Measured as far off (§9 R1), not impossible.
- **AssemblyAI polls forever** → the stage fails with "still processing after
  N", not a hung debrief.
- **AssemblyAI's DELETE fails** → surfaced and logged. The vendor is holding a
  copy of a client's meeting; that is not a detail to swallow.
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
- Both vendors' responses → `BatchTranscriptionOutput`, against **recorded
  fixtures**. No test makes a live call.
- Deepgram's response → `DiarizationOutput`; consecutive same-speaker
  utterances merge into one `SpeakerTurn`.
- Two `COMPLETE` transcripts produce a `SessionAlignment`; one does not.
- The engagement vocabulary reaches each vendor in its own dialect —
  `keyterm` repeated per term for Deepgram, `word_boost` for AssemblyAI.
- `mip_opt_out` on every Deepgram request follows `disable_vendor_retention`,
  and the vocabulary on both vendors follows `keyterm_prompting`; `DELETE`
  issued on every AssemblyAI transcript, including after a failed poll, and an
  upload that never became one reported by name.
- Each vendor's key is resolved and tested against **its own** vendor, not
  against `live_vendor`.
- A selected vendor with no credential, and one with no client at all, each
  fail closed by name on the call. Neither stops the service starting — the
  vendor list comes from a form, and a form entry that bricks a boot also
  takes away the screen it would be corrected on.
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

1. A meeting recorded in the browser at `https://<host>:1420` produces two real
   `RecordPathTranscript`s, one per vendor, and a `SessionAlignment` between
   them showing measured divergence.
2. Its `SessionDiarization` carries real speaker tags, from Deepgram.
3. The debrief runs past step 3 and produces the four documents with citations.
4. The audio is destroyed afterwards and the deletion is in the audit trail.
5. `GET /api/audit/egress` shows one row per vendor call, both vendors.
5a. No AssemblyAI transcript remains on the vendor's side after a run.
6. Full suites green: service, API integration, desktop, ruff, clippy.
7. Journeys 3/6/7 status tables and the handbook chapter they feed are updated
   to say what now works — including that the live path still does not.

---

## 9. Risks

**R1 — Deepgram's processing-time ceiling. CLOSED, measured.**

The concern was real and the measurement retired it. Real speech, resampled to
the 16 kHz mono `linear16` the capture pipeline produces, sent with the exact
query shape §5.4a specifies:

| Audio | Payload | Wall clock | Per audio-minute |
|---|---|---|---|
| 10 min | 19.2 MB | 7 s | 0.7 s |
| 90 min | 172.8 MB | 71 s | 0.8 s |

A full-length meeting finishes in 71 seconds against a 600-second ceiling —
8.5x headroom — and the cost stayed linear rather than degrading with payload
size. **No callback flow is needed.** The same run confirmed the §5.4a response
mapping against 1647 real utterances.

Two things it did not settle, both carried below as R6 and R7.

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

**R6 — AssemblyAI's utterance shape is unobserved.** The §5.4b mapping is read
from documentation, where Deepgram's is read from a real 90-minute response. The
spike proved AssemblyAI's *flow* — upload, poll, `completed`, delete, all 200 —
but on synthetic tone, which produces no speech and therefore no `utterances`.
*Mitigation:* confirm against real speech as the first task of the AssemblyAI
client, before any mapping code is written. It is a five-minute check and it
gates a whole component.

**R7 — Speaker separation is unproven for either vendor.** Both spikes used a
single-narrator sample, so diarization returned exactly one speaker. That
`speaker` is present and well-formed is established; that two people in a room
are told apart is not. *Mitigation:* the live verification in §7 uses a genuine
two-person recording. Until it does, the diarization half of this design rests
on the vendors' claims.

**R8 — Two vendors, two failure surfaces, and cost per meeting doubles.** Every
meeting is now transcribed twice, billed twice, and can fail two ways. The
independence is the point — it is what FR-2.6 buys — but it is a running cost
somebody should have agreed to, not a surprise on an invoice.

**R9 — The Settings screen is being rewritten right now.** §2's credential
changes land in `SettingsPanel.tsx`, which currently has uncommitted work
converting it from a stack of sections into a row of tabs, along with four
regenerated screenshots and two handbook chapters. Implementing per-vendor keys
against the old layout would collide. *Mitigation:* the tabs rewrite lands
first, or the credential work is sequenced behind it deliberately. This is a
scheduling constraint, not a design one, but it will cost a day if ignored.
