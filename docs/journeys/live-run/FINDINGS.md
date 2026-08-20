# Live journey run — what it found

Driven against the running system (panel `http://192.168.99.233:1420`, service
`:8000`) with a real Anthropic OAuth token. Every journey recorded to video and
screenshots.

## The one finding behind almost all the others

**In `apps/service/src/app/composition.py`, write paths and read paths are bound
to different `Backend` fields.** A sweep of the 64 fields the `Backend`
dataclass declares finds **17 that are read and never written** anywhere in
production code:

```
consent_models          confirmed_meetings      egress_rows
nudge_signals           meeting_artifacts       artifacts_by_id
bmad_chains             meeting_base_candidates meeting_inherited_open_questions
candidate_authority_requirements                session_engagement_ids
template_sections       known_meetings          session_stream_events
run_ratings             reference_document_bodies                replay_statuses
```

The only writers are unit-test fakes, which supply the collection themselves —
so every unit test passes while the assembled service cannot work. This is the
failure mode `CLAUDE.md` names: *"Acceptance criteria must fail on the empty
case."* A guard reading a permanently empty set is indistinguishable from a
working guard until something drives it end to end.

The shape repeats exactly: **the write endpoint accepts and returns an id, and
the matching read endpoint 404s or returns empty.**

| Write | Result | Matching read | Result |
|---|---|---|---|
| `POST /api/meetings` | `201 meeting-2` | `GET /api/meetings/meeting-2` | `404 meeting not found` |
| `POST /api/meetings/{id}/consent-confirmation` | `200`, timestamped | `GET .../consent-gate` | still `awaiting_confirmation` |
| `POST /api/engagements/{id}/documents/link` | `201 reference-document-2` | `GET .../documents` | `[]` |
| `POST /api/replay/runs` | `202 run-1` | `GET /api/replay/runs/run-1` | `404 no replay run: run-1` |
| `POST /api/replay/runs/{id}/ratings` | `201 rating-1` | `GET .../metrics` | empty |
| `POST /api/meetings/{id}/record/transcribe` | `202`, two engine lineages | `GET .../record/divergences` | `404 alignment not found` |

Three specific consequences are worth calling out on their own.

### 1. The live meeting path is unreachable — `known_meetings` (critical)

`composition.py:763`, `:778` and `:832` gate `session/start`, `session/stream`
and `slow-lane/tick` on `meeting_id in backend.known_meetings`. `create_meeting`
(`:511`) writes only `backend.meeting_engagement_ids`. **Nothing anywhere writes
`known_meetings.`** Every meeting created through the real API therefore 404s at
`session/start`, so the operator panel — the product's headline feature — can
never receive a stream from a running service.

### 2. The consent gate never opens — `confirmed_meetings` (critical, safety)

`is_confirmed_for_meeting` (`:395`) returns `meeting_id in
backend.confirmed_meetings`. `save_consent_record` (`:397`) appends to
`backend.consent_records` and never touches `confirmed_meetings`. Consent is
recorded correctly and read back as never given.

This is safety-relevant in both directions: today it fails closed, but the two
halves of the gate are not connected, so nothing in the assembled service
demonstrates the gate works at all. Journey 2's "session refused before consent"
only passes because the service cannot find the meeting — a 4xx for the wrong
reason.

### 3. The debrief conversation is a stub that looks like an answer (high)

`composition.py:609-610`:

```python
async def send_debrief_message(conversation_ref: str, message: str) -> list[dict[str, Any]]:
    backend.sent_messages.append((conversation_ref, message))
    return [{"type": "text", "text": f"ack: {message}"}]
```

The conversational debrief never calls a model. `main.py` builds
`debrief_engines` from the settings store and passes them to `build_app`, and
this function ignores them. On screen the operator sees Elicta reply
**"ack: Which requirements are still only inferred?"** — rendered identically to
a real answer.

This inverts the principle `CLAUDE.md` states: *"The default raises rather than
returning plausible output, so an unconfigured deployment fails honestly instead
of looking healthy."* Here it returns plausible output and looks healthy.

### 4. The compiler reads filenames, not documents (high)

`_run_engagement_compile` (`:1196`) builds its extraction input as
`ExtractionSourceDocument(document_id=…, text=document.name)` — the document's
**name**. The text is held in `backend.reference_document_bodies`, which is
never read here. `context_pack` is built with `documents=[]` hardcoded.
Linked SharePoint documents are not included at all, because they land in
`reference_documents` while the compiler reads `engagement_documents`.

That is why `POST /bank/compile` returns a job id and the bank stays empty.

## Why the existing suites do not catch any of this

`uv run --project apps/service python -m pytest tests/e2e/api_integration` —
**45 passed in 3.95s**, while the assembled service cannot complete a single
journey.

The suite genuinely drives the production composition root, as `CLAUDE.md`
says. What it does not do is connect a write to its matching read. It reaches
into the backend and hand-places state in the very fields the composition root
never fills:

```python
backend.replay_statuses["run-1"] = ReplayRunStatusResponse(...)   # test_replay.py:41
backend.meeting_artifacts["m1"]  = [...]                          # test_debrief.py:119
backend.artifacts_by_id["a1"]    = ArtifactDetail(...)            # test_debrief.py:132
backend.consent_models["e1"]     = ConsentModel.PER_MEETING       # test_consent_and_egress.py:12
backend.bmad_chains["s1"]        = _complete_chain()              # test_debrief.py:246
```

and it asserts writes landed in *their* field:

```python
assert len(backend.replay_ratings) == 1                           # test_replay.py:19
```

`replay_ratings` is the field the write goes to; `run_ratings` is the field the
metrics endpoint reads. Both halves of the feature are tested, independently,
and the seam between them is never crossed. Every finding above lives in exactly
that seam.

A test that creates a meeting through the API and then starts a session on it
would have failed on day one.

## Six screens are not connected to anything

`prep`, `consent`, `recording`, `replay`, `arc` and `debrief` each export a
`route.tsx` default that renders its component with hardcoded empty props —
`clientOrganisation="—"`, `bank={null}`, `divergences={[]}`, `meetings={[]}`,
`suggestions={[]}`. The components are complete and take real props; nothing in
the running app supplies them. Only `journeys.html`, the fixed-scene harness,
does — which is why the documentation screenshots look fully populated and the
running app does not.

`debrief-chat` is wired, but to a hardcoded `useDebriefChat('meeting-1')`.

## What genuinely works, live

- **Settings, end to end (7/7).** Entering the OAuth token in the real UI, saving
  it, and testing it produced `reachable: true` against Anthropic's API. The
  write-only secret contract holds: the response carries a four-character hint,
  never the value, and the raw token appears nowhere in the payload.
- **Input validation is real.** `term_type` is enum-checked; a document link is
  rejected unless it is a SharePoint or Teams URL.
- **Consent records are captured properly** — named confirmer, ISO timestamp,
  and a gate prompt that states its legal basis.
- **Two screens degrade honestly.** Capture says "Audio capture is unavailable
  outside the desktop app, so nothing is being recorded" and disables the
  control. About distinguishes "Signature not checked" from "Unsigned" in words.
- **The consent screen's own gate works** — its Start button is disabled until
  consent is confirmed.

## The speech path: the key was never the blocker

A Deepgram key was supplied and configured through the real Settings screen —
selected as the live vendor, stored, and **verified against Deepgram**
(`Verified (…8285)` on screen, `reachable: true` from the probe). The service's
probe hits `GET https://api.deepgram.com/v1/projects`, which returns 200.

The key also transcribes. Streaming a live radio feed into Deepgram's v2 Flux
endpoint the way the vendor's own sample does — ffmpeg to 16kHz mono PCM16,
frames straight up the socket — produced continuous, accurate transcript from
1.33 MB of audio, including the progressively revised partials that are
characteristic of Deepgram.

**None of that reaches Elicta, because Elicta has no Deepgram client.**

- **Live path.** `TranscriptionBackend` in `core/crates/asr-live` is the vendor
  seam. It has exactly three implementations — `ImmutablePartialFakeBackend`,
  `RevisablePartialFakeBackend` and `PrematureEndpointFakeBackend` — and **all
  three are fakes**. The crate's `Cargo.toml` declares *no dependencies at all*,
  so it has no websocket client and physically cannot connect to a vendor. Every
  `wss://api.deepgram.com/v1/listen` string in the crate is inside a test
  assertion about URL construction.
- **Record path.** `app/modules/asr-record` contains no HTTP client and makes no
  outbound call. `POST /record/transcribe` returns a queued job with
  `engine_lineages: ["engine-a", "engine-b"]` — placeholder names — and nothing
  ever transcribes.

The crate's own `HANDOFF.md` says so plainly: *"a real `DeepgramBackend` /
`AssemblyAiBackend` implements `TranscriptionBackend` the same way the fakes
here do"* — written as future work. There is a nice irony in
`RevisablePartialFakeBackend` being documented as "mimicking Deepgram-style
revised partials": the live stream above produced exactly that behaviour, from
the real vendor, which the product can only imitate.

So journeys 3, 4 and 6 fail for a reason one level deeper than a credential:
the vendor integration does not exist. Journey 11 is separate again — audio
capture is a desktop-shell capability, unavailable in a browser, and the screen
says so correctly.

## What changed once the key was configured

| Check | Before | After |
|---|---|---|
| `asr_vendor_api_key` configured | no | **yes** |
| Deepgram credential verified against the vendor | not run | **passes** |
| Live vendor selectable and persisted as Deepgram | not run | **passes** |
| Speech key is write-only (hint only, never the value) | not run | **passes** |
| Journey 10 overall | 7 of 7 | **12 of 12** |
| Anything actually transcribed by Elicta | no | **still no** |
