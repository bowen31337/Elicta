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

---

# What was closed — 20 August 2026

Thirteen stories, run through the autonomous agent loop
(`scripts/ralph/`), each one reconnecting a seam and proving it with a
test that goes through the API in both directions. Re-running the same
harness against the same system afterwards:

**52 passed / 34 failed → 67 passed / 21 failed.** Journeys 2, 5 and 10
now pass completely.

| # | Journey | Before | After |
|---|---|---|---|
| 01 | Prepare for the engagement | 7P/5F | 12P/1F |
| 02 | Start the meeting, with consent | 8P/4F | **13P/0F** |
| 03 | Catch a vague answer | 2P/3F | 3P/2F |
| 04 | Two languages | 4P/1F | 4P/1F |
| 05 | When the connection drops | 3P/1F | **4P/0F** |
| 06 | Check the recording | 1P/3F | 3P/1F |
| 07 | Get the write-up | 6P/8F | 4P/10F |
| 08 | Carry state forward | 2P/4F | 3P/3F |
| 09 | Judge the suggestions | 3P/3F | 5P/1F |
| 10 | Set up the services | 12P/0F | **12P/0F** |
| 11 | Control the recording | 2P/1F | 2P/1F |
| 12 | Install and roll out | 2P/1F | 2P/1F |

Every write/read pair in the table at the top of this document now works.
Verified against a service running the new code, not only in tests:

- `POST /api/meetings` → `GET /api/meetings/{id}` returns the meeting
- consent-confirmation → consent-gate reads `confirmed`, and a session
  started before consent is refused **naming consent**, not "meeting not
  found"
- a linked document appears in the engagement's document list
- a replay run reads back, and a rating moves its metrics
- transcribe → divergences returns a result

The `ack:` stub is gone. With no model configured the debrief returns
**503** naming what is missing; under a provider rate limit it returns
**429** with `retry_after` and the sentence "this is a limit, not a
fault." The egress audit records rows, including failures with reasons.

The six unwired screens read from the service, and a toolbar control
chooses which engagement and meeting they are about — `select()` existed
but no component called it, so until that control was added every screen
showed whatever the oldest engagement held.

## Two of the thirteen stories were found by verifying, not by reading

Eleven stories came from this document. Two did not, and they are the
argument for re-running the harness rather than trusting a green suite:

- **The screens were wired to nothing selectable.** After the six screens
  were connected, `useCurrentEngagement` exposed `select()` and *no
  component called it* — there was no picker. The app fell back to the
  first engagement the service returned, which on this machine was the
  oldest and had no meetings, so every screen honestly reported it had
  nothing to show. A test asserting "the screen renders" would have
  passed throughout.
- **A rate limit looked like a broken deployment.** With the `ack:` stub
  removed, the debrief called Claude for real — and an
  `anthropic.RateLimitError` escaped as a bare `500 Internal Server
  Error`, while the unconfigured case correctly returned 503 naming what
  was missing. Two failures that need opposite responses from an operator
  looked identical.

Neither was visible in the code review that produced the first eleven
stories. Both appeared the first time the whole thing was driven.

## What the harness got wrong

Three faults in the test, not the product, each of which made the product
look worse than it was. They are recorded because the before-and-after
numbers cannot be read honestly without them.

- **`reloadTo` never reloaded.** It navigated to a URL differing only in
  its fragment, which Chrome treats as a same-document change: the hash
  moved and the document did not reload, so the toolbar picker kept the
  engagement list it fetched at first mount. Setting a `<select>` to a
  value with no matching option leaves the old value silently, so the run
  reported the picker reading `eng-1` after choosing `eng-10` — and the
  screens looked unwired when they were not.
- **The consent gate was asserted in one state only.** Journey 2 checked
  that the Start button was disabled *after* consent had been confirmed.
  It passed originally because the screen was hardcoded to
  `confirmedBy={null}` — for the wrong reason entirely. It now reads the
  screen before consent and again after, so it tests the transition. A
  gate observed in a single state is not being tested.
- **Checks passed on non-empty strings.** The first run scored the panel
  as showing coverage because `— / —` is not the empty string, and scored
  the debrief as answering because two conversation turns existed — one
  of which was `ack:` echoing the question back. Those were tightened
  before the baseline in this document was recorded.

## The guard that makes this stay closed

`apps/service/src/app/test_composition_seams.py` asserts the structural
invariant: **a field the composition root reads, it must also write**, or
it appears in `ACCEPTED_READ_ONLY` with a stated reason. Both halves are
mutation-tested — introducing a new read-only field fails the invariant
test, and adding a `backend.*` assignment to a seam test fails
`test_no_seam_test_sets_up_its_own_read_side`.

Suites: 706 → 792 service tests, 45 → 107 API integration, 199 → 363
desktop.

## What is still open, and why

None of the 21 remaining failures is unfinished work from this pass.

- **Ten (journey 7) are an Anthropic rate limit.** The debrief now
  returns 429 with the message above; the journey still cannot complete
  without a model, and the artifacts downstream of it cannot be produced.
- **Six need something that does not exist.** The live panel, language
  chrome, audio sources and OS permissions require either the
  speech-vendor backend — `TranscriptionBackend` still has three
  implementations and all three are fakes — or the desktop shell, which a
  browser is not.
- **Four are accepted exceptions**, each named with its reason in
  `ACCEPTED_READ_ONLY`: inherited open questions and the per-meeting bank
  need a recompile step no caller runs; a linked document's body needs a
  connector that does not exist.
- **One is the compiler**, which now reads document *text* rather than
  filenames but has no text to read until that connector exists.

The handbook is in drift on seven chapters, because the screens they show
changed. That is the mechanism working; it needs a human to re-read them
and run `gen.py accept`.

---

# Re-run — 21 August 2026

**56 passed / 28 failed**, clean state database, real Anthropic OAuth token, no
Deepgram key, `ELICTA_INFERENCE_MODEL=claude-haiku-4-5-20251001`.

Journey 1 is 13 of 14. The preparation screen now does what journey 1 says it
does — create the engagement, add documents by dropping a file or by link, tag
them, keep the vocabulary list, reorder and prune the bank — and the live run
drives all of it. Its one failure is the question bank, which cannot be drafted
on this credential.

## What the run found about the credential, not the code

The first re-run reported "rate limited" and "the provider rejected the
configured credential". Both were wrong, and both were the product's own
wording rather than the provider's:

| Probe | Result |
|---|---|
| `GET /v1/models` | 200 |
| `POST /v1/messages` — `claude-haiku-4-5-20251001` | **200** |
| `POST /v1/messages` — opus-5 / sonnet-5 / fable-5 | 429, **no `retry-after`, no rate-limit headers** |
| `POST /v1/messages/batches` | **403** `permission_error`, naming the scopes it wanted |

So: the token is valid; the *default model* is not on its plan, and the Batch
API needs a scope it does not carry. Anthropic signals the first as
`rate_limit_error`, which is indistinguishable from throttling unless you
notice there is no retry hint — and the product was actively telling the
operator "the same request should succeed shortly", which was never true.

Three reporting defects were fixed as a result: a 403 scope error is now its own
`NOT_ENTITLED` failure carrying the provider's sentence rather than "re-enter
your credential"; a 429 with no retry hint says the model may not be one this
credential can use; and `ELICTA_INFERENCE_MODEL` — the documented way out — was
dead, because it was only read when the settings model was falsy and that field
defaults to `claude-opus-5`.

## What is still open

* **A bank drafted by a real provider has not been seen.** The submission is
  refused for want of a scope. The collector that goes back for a finished
  batch is built, tested and started by the process, and is proven against a
  stand-in batch that finishes on the second sweep.
* **Consent is fail-open.** `DEFAULT_CONSENT_MODEL = ENGAGEMENT_LEVEL` means the
  gate answers `not_required`, a session starts unconfirmed, and no
  `ConsentRecord` is written. Journey 2 fails on exactly that (13/0 → 8/5). The
  decision is deliberate and documented at the constant; this is the harness
  reporting it, not a regression in it.
* **No speech vendor client exists** on either path, and this run had no
  Deepgram key configured.
* **The engagement picker lists 20.** An earlier attempt at this run failed
  journey 1's toolbar check because the state database had accumulated 28
  engagements and `eng-28` was not in the list. Real for any deployment past
  twenty; the run was redone against a clean database.


---

# Re-run after the storage work — 21 August 2026

**65 passed / 19 failed**, up from 56/28 earlier the same day. Same clean state
database, same credential, same model override.

| Journey | Earlier | Now | Why |
|---|---|---|---|
| 01 Prepare | 13P/1F | **16P/1F** | Three new checks: a vocabulary term is removed, the removal takes effect, and removing an id nobody has is a 404 rather than a cheerful 204 |
| 02 Consent | 8P/5F | **10P/0F** | The journey was rewritten to assert what this build does — see below |
| 07 Write-up | 4P/10F | **8P/6F** | The debrief reaches a model it is entitled to and answers for real; the remaining six are the artifacts downstream of it |

## What the run now proves that it could not before

* **What an operator types is kept.** Documents and vocabulary are written to
  SQLite as they are added, and the screenshot for journey 1 shows them read
  back from the database rather than held in a process.
* **A removal is real and is soft.** The run adds a deliberately mistyped
  keyterm, removes it, and the screenshot shows the three correct words with the
  typo gone — while the row is still in the database, marked.
* **A 404 for an id nobody has.** Answering 204 to any delete would make a typo
  look like a successful removal, which is the failure mode a soft delete is
  least able to survive: nothing is erased, so nothing looks wrong.

## Journey 2 passing 10/10 does not mean consent is on the record

`DEFAULT_CONSENT_MODEL` is `ENGAGEMENT_LEVEL`, so the gate answers
`not_required`, a session starts with nothing confirmed and no `ConsentRecord`
is written. The journey now asserts that behaviour rather than the asking one,
which is the honest thing for a harness to do — but it means a green journey 2
records that consent is *not being asked for*, not that it was obtained. The
decision is deliberate and documented at the constant.

## Still open

* A bank drafted end to end by a real provider: the credential cannot submit a
  batch job at all.
* Erasing a client's data outright. Removal is soft everywhere, on purpose: real
  erasure would have to decide about recordings, consent records and debrief
  artifacts, and the PRD asks for none of it.
* The engagement list shows the first twenty.

## What the 21 August re-run added

Two findings that only a live run could produce, both from journey 5.

**The panel's degraded badge could not detect a connection dropping.** Its mode
came from whether a provider was *configured* — a fact fixed when the service
started. An outage, an expired credential, a throttle and a revoked scope all
left it reporting the model as reachable. It now comes from what real calls
found. The credential here supplies the proof: it is accepted on
`POST /v1/messages` and refused on `/v1/messages/batches` for want of a scope,
which is a genuine upstream failure across a genuine seam.

**And the first version of that fix was wrong, in a way only the live run
showed.** The observation was wired into the audit wrapper both the compiler and
the debrief engines share, so the batch refusal above — a *pre-meeting* compile,
on a different entitlement — put the live panel into degraded mode about a model
that was answering fine. Journey 5's oldest check, "the panel is not falsely
claiming degraded mode while the model is reachable", went red the first time it
ran end to end. Every unit test still passed: each was scoped to one seam, and
the defect was that two seams shared one opinion.

**A third, about the harness rather than the product.** Chrome was launched with
no `--user-data-dir`, so `localStorage` — where the toolbar keeps the chosen
engagement — survived between runs. Against a fresh state database the picker
opened holding the previous run's id, and journey 1 failed on the toolbar check
in a way that read as a regression in the picker. Each run now gets a profile of
its own and deletes it afterwards.

