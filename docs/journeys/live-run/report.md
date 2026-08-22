# Live journey run

Driven against a running system — panel at http://127.0.0.1:1420, service at http://127.0.0.1:8000.
**72 of 89 checks passed; 17 failed.**

| # | Journey | Passed | Failed | Recording |
|---|---|---|---|---|
| 01 | Prepare for the engagement | 16 | 1 | `01-prepare-an-engagement/journey.mp4` |
| 02 | Start the meeting, with consent on the record | 10 | 0 | `02-start-a-meeting-with-consent/journey.mp4` |
| 03 | Catch a vague answer while it still matters ⚠︎ | 4 | 2 | `03-catch-a-vague-answer-live/journey.mp4` |
| 04 | Run a meeting in two languages ⚠︎ | 3 | 2 | `04-run-a-code-switched-meeting/journey.mp4` |
| 05 | When the connection drops | 8 | 0 | `05-degraded-mode/journey.mp4` |
| 06 | Check the recording ⚠︎ | 4 | 0 | `06-reconcile-the-recording/journey.mp4` |
| 07 | Get the write-up | 8 | 6 | `07-produce-the-debrief/journey.mp4` |
| 08 | Carry what you learned forward | 3 | 3 | `08-carry-state-forward/journey.mp4` |
| 09 | Judge whether the suggestions are any good | 5 | 1 | `09-replay-and-tune-ranking/journey.mp4` |
| 10 | Set up the services Elicta uses | 7 | 0 | `10-configure-providers/journey.mp4` |
| 11 | Control the recording | 2 | 1 | `11-control-capture/journey.mp4` |
| 12 | Get Elicta onto people’s machines | 2 | 1 | `12-install-and-roll-out/journey.mp4` |

⚠︎ — journey depends on a speech-vendor credential that is not configured.

## 01 — Prepare for the engagement

Video: `01-prepare-an-engagement/journey.mp4` (272 frames). Screenshots: 1.

**Passed**

- engagement is created
- the service returns an engagement id
- all three vocabulary terms are accepted
- an unknown term type is rejected rather than stored
- a link that is not a Microsoft 365 one is refused
- a link is either read or refused, never attached unread
- an uploaded document is accepted
- the uploaded document appears in the document list
- a vocabulary term can be removed
- the removed word is gone and the others are not
- removing something that is not there is not reported as success
- compilation is accepted
- the engagement can be chosen from the toolbar
- the preparation screen names the client organisation
- the screen lists the reference document just attached
- the screen shows the engagement vocabulary just added

**Failed**

- **the compiled bank contains candidate questions**
  - bank after compile: {"engagement_id":"eng-1","sections":[],"generated_at":"2026-08-21T10:15:00.941186Z"}

## 02 — Start the meeting, with consent on the record

Video: `02-start-a-meeting-with-consent/journey.mp4` (113 frames). Screenshots: 1.

**Passed**

- the meeting is created
- the meeting carries its engagement context
- the gate reports that consent is not being asked for
- a gate that is not asking carries no prompt
- the screen says consent is not required for this meeting
- the screen does not claim anything is on record
- capture can be started with nothing confirmed — the stage default
- the session starts without a consent confirmation
- no consent record is written when consent was never asked for
- the consent screen names the meeting it gates

- note — the asking consent model is not reachable over the API: no endpoint sets an engagement consent model, so this run exercises the engagement-level default only; the per-meeting gate is covered in the API suite

Failed browser requests during this journey: 1

- `404 http://127.0.0.1:1420/api/meetings/meeting-1/consent-record`

## 03 — Catch a vague answer while it still matters

> Blocked: No Deepgram backend exists. `TranscriptionBackend` has three implementations in `core/crates/asr-live` and all three are fakes; the crate has no dependencies, so it cannot open a socket.

Video: `03-catch-a-vague-answer-live/journey.mp4` (104 frames). Screenshots: 1.

**Passed**

- the session stream is reachable
- the slow lane accepts a tick
- the panel renders
- the panel opens the meeting’s live session stream

**Failed**

- **the panel shows live coverage from the session**
  - coverage chrome reads "— / —" — the stream is open, but nothing writes session_stream_events, so the session carries no coverage
- **a follow-up question is surfaced to the operator**
  - nudge area reads "No active nudge" — no utterance exists to trigger on, because every transcription backend in asr-live is a test double

## 04 — Run a meeting in two languages

> Blocked: Same missing vendor backend as journey 3 — the credential is configured and verified, but nothing can connect to Deepgram to transcribe.

Video: `04-run-a-code-switched-meeting/journey.mp4` (58 frames). Screenshots: 1.

**Passed**

- the panel reports which languages are being heard
- keyterm prompting is on, so client terms survive transcription
- a live transcription vendor is selected

**Failed**

- **the selected speech vendor has a credential**
  - asr_vendor_api_key configured: false
- **the speech vendor accepts the configured credential**
  - {"key":"asr_vendor_api_key","reachable":false,"detail":"No credential is configured."}

## 05 — When the connection drops

Video: `05-degraded-mode/journey.mp4` (188 frames). Screenshots: 1.

**Passed**

- the panel is not falsely claiming degraded mode while the model is reachable
- the configured model credential is reachable
- an egress audit trail is available
- the audit records what left the machine
- the stream tells the panel which mode it is in, before anything else
- a reachable provider is reported as reachable, from a real call rather than from setup
- a refused batch does not put the live panel into degraded mode
- a meeting with no debrief run is not reported as a failed one

## 06 — Check the recording

> Blocked: `app/modules/asr-record` makes no outbound HTTP call, so the record path has no vendor client to reconcile two engines with.

Video: `06-reconcile-the-recording/journey.mp4` (95 frames). Screenshots: 1.

**Passed**

- the record path accepts a transcription request
- divergences between the two engines are reported
- the screen names the engines that transcribed the meeting
- the screen reports how far the engines agreed

## 07 — Get the write-up

Video: `07-produce-the-debrief/journey.mp4` (453 frames). Screenshots: 5.

**Passed**

- a debrief conversation opens
- the conversation is anchored to a session
- the debrief accepts a free-text question
- the answer comes from the model rather than a stub echo
- the conversation opens from the screen
- the screen shows the question and an answer
- the answer on screen is a real answer, not the question echoed back
- the debrief screen reports no error

**Failed**

- **the project brief is produced**
  - status 404, {"detail":"draft project brief not found"}
- **the decision log is produced**
  - status 404, {"detail":"decision log not found"}
- **the open questions is produced**
  - status 404, {"detail":"open questions list not found"}
- **the follow-up email is produced**
  - status 404, {"detail":"draft follow-up email not found"}
- **the meeting lists its artifacts**
  - []
- **every claim on the debrief screen carries its citation**
  - 0 cited claims rendered

Failed browser requests during this journey: 3

- `404 http://127.0.0.1:1420/api/sessions/meeting-1/open-questions`
- `404 http://127.0.0.1:1420/api/sessions/meeting-1/decision-log`
- `404 http://127.0.0.1:1420/api/sessions/meeting-1/project-brief`

## 08 — Carry what you learned forward

Video: `08-carry-state-forward/journey.mp4` (88 frames). Screenshots: 1.

**Passed**

- engagement state is readable
- a second meeting is created in the same engagement
- the arc shows the meetings held so far

**Failed**

- **open questions are carried forward to the next meeting**
  - state reads {"engagement_id":"eng-1","inherited_open_questions":[],"requirements_state":null}
- **the requirements state is readable**
  - status 404, {"detail":"requirements state not found"}
- **the second meeting inherits candidate questions**
  - inherited bank: {"meeting_id":"meeting-2","candidates":[],"generated_at":"2026-08-21T10:16:54.528775Z"}

## 09 — Judge whether the suggestions are any good

Video: `09-replay-and-tune-ranking/journey.mp4` (57 frames). Screenshots: 1.

**Passed**

- a replay run starts
- the run reports its suggestions
- a rating is accepted
- the run reports the precision and embarrassment gates
- the replay screen names the run it is showing

**Failed**

- **the screen lists suggestions to rate**
  - 0 suggestions rendered

## 10 — Set up the services Elicta uses

Video: `10-configure-providers/journey.mp4` (275 frames). Screenshots: 5.

**Passed**

- settings load from the service
- the credential field never renders its value
- the screen confirms the save
- the service stores the token
- a stored secret is never returned, only hinted at
- the screen reports the credential verified
- a live transcription vendor can be chosen

## 11 — Control the recording

Video: `11-control-capture/journey.mp4` (40 frames). Screenshots: 1.

**Passed**

- the capture state is stated in words, not colour alone
- an unavailable audio backend is explained rather than left looking like a choice

**Failed**

- **the screen lists the audio sources it can record from**
  - 0 sources listed

- note — capture in a browser: pause control disabled: true; reason shown: "No microphone is available to this browser. Connect one — or allow access if it was refused — and it will appear here."

## 12 — Get Elicta onto people’s machines

Video: `12-install-and-roll-out/journey.mp4` (40 frames). Screenshots: 1.

**Passed**

- the build identifies its version and platform
- the signing state is stated, and unknown is distinguished from unsigned

**Failed**

- **the OS permissions this build holds are listed**
  - 0 permission rows rendered
