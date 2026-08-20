# Live journey run

Driven against a running system — panel at http://127.0.0.1:1420, service at http://127.0.0.1:8000.
**67 of 88 checks passed; 21 failed.**

| # | Journey | Passed | Failed | Recording |
|---|---|---|---|---|
| 01 | Prepare for the engagement | 12 | 1 | `01-prepare-an-engagement/journey.mp4` |
| 02 | Start the meeting, with consent on the record | 13 | 0 | `02-start-a-meeting-with-consent/journey.mp4` |
| 03 | Catch a vague answer while it still matters ⚠︎ | 3 | 2 | `03-catch-a-vague-answer-live/journey.mp4` |
| 04 | Run a meeting in two languages ⚠︎ | 4 | 1 | `04-run-a-code-switched-meeting/journey.mp4` |
| 05 | When the connection drops | 4 | 0 | `05-degraded-mode/journey.mp4` |
| 06 | Check the recording ⚠︎ | 3 | 1 | `06-reconcile-the-recording/journey.mp4` |
| 07 | Get the write-up | 4 | 10 | `07-produce-the-debrief/journey.mp4` |
| 08 | Carry what you learned forward | 3 | 3 | `08-carry-state-forward/journey.mp4` |
| 09 | Judge whether the suggestions are any good | 5 | 1 | `09-replay-and-tune-ranking/journey.mp4` |
| 10 | Set up the services Elicta uses | 12 | 0 | `10-configure-providers/journey.mp4` |
| 11 | Control the recording | 2 | 1 | `11-control-capture/journey.mp4` |
| 12 | Get Elicta onto people’s machines | 2 | 1 | `12-install-and-roll-out/journey.mp4` |

⚠︎ — journey depends on a speech-vendor credential that is not configured.

## 01 — Prepare for the engagement

Video: `01-prepare-an-engagement/journey.mp4` (197 frames). Screenshots: 1.

**Passed**

- engagement is created
- the service returns an engagement id
- all three vocabulary terms are accepted
- an unknown term type is rejected rather than stored
- a non-SharePoint link is refused
- a SharePoint link is attached
- the attached document appears in the document list
- compilation is accepted
- the engagement can be chosen from the toolbar
- the preparation screen names the client organisation
- the screen lists the reference document just attached
- the screen shows the engagement vocabulary just added

**Failed**

- **the compiled bank contains candidate questions**
  - bank after compile: {"engagement_id":"eng-13","sections":[],"generated_at":"2026-08-20T05:56:10.511292Z"}

## 02 — Start the meeting, with consent on the record

Video: `02-start-a-meeting-with-consent/journey.mp4` (208 frames). Screenshots: 2.

**Passed**

- the meeting is created
- the meeting carries its engagement context
- the gate reports consent is still awaited
- the gate states its legal basis
- starting a session before consent is refused
- the refusal is about consent, not a meeting the service cannot find
- capture cannot be started until consent is confirmed
- consent is recorded against a named person
- consent is timestamped
- the gate opens once consent is confirmed
- the session starts once consent is confirmed
- capture becomes available once consent is on the record
- the consent screen names the meeting it gates

Failed browser requests during this journey: 1

- `404 http://127.0.0.1:1420/api/meetings/meeting-9/consent-record`

## 03 — Catch a vague answer while it still matters

> Blocked: No Deepgram backend exists. `TranscriptionBackend` has three implementations in `core/crates/asr-live` and all three are fakes; the crate has no dependencies, so it cannot open a socket.

Video: `03-catch-a-vague-answer-live/journey.mp4` (59 frames). Screenshots: 1.

**Passed**

- the session stream is reachable
- the slow lane accepts a tick
- the panel renders

**Failed**

- **the panel shows live coverage from the session**
  - coverage chrome reads "— / —"
- **a follow-up question is surfaced to the operator**
  - nudge area reads "No active nudge"

## 04 — Run a meeting in two languages

> Blocked: Same missing vendor backend as journey 3 — the credential is configured and verified, but nothing can connect to Deepgram to transcribe.

Video: `04-run-a-code-switched-meeting/journey.mp4` (67 frames). Screenshots: 1.

**Passed**

- keyterm prompting is on, so client terms survive transcription
- a live transcription vendor is selected
- the selected speech vendor has a credential
- the speech vendor accepts the configured credential

**Failed**

- **the panel reports which languages are being heard**
  - language chrome reads "No language detected"

## 05 — When the connection drops

Video: `05-degraded-mode/journey.mp4` (63 frames). Screenshots: 1.

**Passed**

- the panel is not falsely claiming degraded mode while the model is reachable
- the configured model credential is reachable
- an egress audit trail is available
- the audit records what left the machine

## 06 — Check the recording

> Blocked: `app/modules/asr-record` makes no outbound HTTP call, so the record path has no vendor client to reconcile two engines with.

Video: `06-reconcile-the-recording/journey.mp4` (94 frames). Screenshots: 1.

**Passed**

- the record path accepts a transcription request
- divergences between the two engines are reported
- the screen names the engines that transcribed the meeting

**Failed**

- **the screen reports how far the engines agreed**
  - agreement reads "0%"

## 07 — Get the write-up

Video: `07-produce-the-debrief/journey.mp4` (460 frames). Screenshots: 5.

**Passed**

- a debrief conversation opens
- the conversation is anchored to a session
- the answer comes from the model rather than a stub echo
- the conversation opens from the screen

**Failed**

- **the debrief accepts a free-text question**
  - status 429, {"detail":"the debrief conversation (FR-7.3): the model provider is rate limiting this deployment. The same request should succeed shortly — this is a limit, not a fault."}
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
- **the screen shows the question and an answer**
  - 1 turns rendered
- **the answer on screen is a real answer, not the question echoed back**
  - Elicta replied null
- **the debrief screen reports no error**
  - error region reads "the debrief conversation (FR-7.3): the model provider is rate limiting this deployment. The same request should succeed shortly — this is a limit, not a fault. Nothing was lost — ask again when it is back."
- **every claim on the debrief screen carries its citation**
  - 0 cited claims rendered

Failed browser requests during this journey: 4

- `429 http://127.0.0.1:1420/api/meetings/meeting-9/debrief/message`
- `404 http://127.0.0.1:1420/api/sessions/meeting-9/open-questions`
- `404 http://127.0.0.1:1420/api/sessions/meeting-9/decision-log`
- `404 http://127.0.0.1:1420/api/sessions/meeting-9/project-brief`

## 08 — Carry what you learned forward

Video: `08-carry-state-forward/journey.mp4` (89 frames). Screenshots: 1.

**Passed**

- engagement state is readable
- a second meeting is created in the same engagement
- the arc shows the meetings held so far

**Failed**

- **open questions are carried forward to the next meeting**
  - state reads {"engagement_id":"eng-13","inherited_open_questions":[],"requirements_state":null}
- **the requirements state is readable**
  - status 404, {"detail":"requirements state not found"}
- **the second meeting inherits candidate questions**
  - inherited bank: {"meeting_id":"meeting-10","candidates":[],"generated_at":"2026-08-20T05:57:58.367029Z"}

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

Video: `10-configure-providers/journey.mp4` (474 frames). Screenshots: 8.

**Passed**

- settings load from the service
- the credential field never renders its value
- the screen confirms the save
- the service stores the token
- a stored secret is never returned, only hinted at
- the screen reports the credential verified
- a live transcription vendor can be chosen
- Deepgram can be selected as the live vendor
- the service stores the speech-vendor key
- the live vendor is now Deepgram
- the speech key is write-only too, like the model credential
- the screen reports the Deepgram credential verified

## 11 — Control the recording

Video: `11-control-capture/journey.mp4` (40 frames). Screenshots: 1.

**Passed**

- the capture state is stated in words, not colour alone
- an unavailable audio backend is explained rather than left looking like a choice

**Failed**

- **the screen lists the audio sources it can record from**
  - 0 sources listed

- note — capture in a browser: pause control disabled: true; reason shown: "Audio capture is unavailable outside the desktop app, so nothing is being recorded."

## 12 — Get Elicta onto people’s machines

Video: `12-install-and-roll-out/journey.mp4` (40 frames). Screenshots: 1.

**Passed**

- the build identifies its version and platform
- the signing state is stated, and unknown is distinguished from unsigned

**Failed**

- **the OS permissions this build holds are listed**
  - 0 permission rows rendered
