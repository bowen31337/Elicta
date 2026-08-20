# Live journey run

Driven against a running system — panel at http://192.168.99.233:1420, service at http://192.168.99.233:8000.
**52 of 86 checks passed; 34 failed.**

| # | Journey | Passed | Failed | Recording |
|---|---|---|---|---|
| 01 | Prepare for the engagement | 7 | 5 | `01-prepare-an-engagement/journey.mp4` |
| 02 | Start the meeting, with consent on the record | 8 | 4 | `02-start-a-meeting-with-consent/journey.mp4` |
| 03 | Catch a vague answer while it still matters ⚠︎ | 2 | 3 | `03-catch-a-vague-answer-live/journey.mp4` |
| 04 | Run a meeting in two languages ⚠︎ | 4 | 1 | `04-run-a-code-switched-meeting/journey.mp4` |
| 05 | When the connection drops | 3 | 1 | `05-degraded-mode/journey.mp4` |
| 06 | Check the recording ⚠︎ | 1 | 3 | `06-reconcile-the-recording/journey.mp4` |
| 07 | Get the write-up | 6 | 8 | `07-produce-the-debrief/journey.mp4` |
| 08 | Carry what you learned forward | 2 | 4 | `08-carry-state-forward/journey.mp4` |
| 09 | Judge whether the suggestions are any good | 3 | 3 | `09-replay-and-tune-ranking/journey.mp4` |
| 10 | Set up the services Elicta uses | 12 | 0 | `10-configure-providers/journey.mp4` |
| 11 | Control the recording | 2 | 1 | `11-control-capture/journey.mp4` |
| 12 | Get Elicta onto people’s machines | 2 | 1 | `12-install-and-roll-out/journey.mp4` |

⚠︎ — journey depends on a speech-vendor credential that is not configured.

## 01 — Prepare for the engagement

Video: `01-prepare-an-engagement/journey.mp4` (141 frames). Screenshots: 1.

**Passed**

- engagement is created
- the service returns an engagement id
- all three vocabulary terms are accepted
- an unknown term type is rejected rather than stored
- a non-SharePoint link is refused
- a SharePoint link is attached
- compilation is accepted

**Failed**

- **the attached document appears in the document list**
  - list returned {"engagement_id":"eng-6","documents":[]} after attaching reference-document-6
- **the compiled bank contains candidate questions**
  - bank after compile: {"engagement_id":"eng-6","sections":[],"generated_at":"2026-08-20T03:22:10.262912Z"}
- **the preparation screen names the client organisation**
  - heading reads "—"
- **the screen lists the reference document just attached**
  - 0 rows in the reference-documents section
- **the screen shows the engagement vocabulary just added**
  - 0 vocabulary chips rendered

## 02 — Start the meeting, with consent on the record

Video: `02-start-a-meeting-with-consent/journey.mp4` (85 frames). Screenshots: 1.

**Passed**

- the meeting is created
- the meeting carries its engagement context
- the gate reports consent is still awaited
- the gate states its legal basis
- starting a session before consent is refused
- consent is recorded against a named person
- consent is timestamped
- capture cannot be started until consent is confirmed

**Failed**

- **the refusal is about consent, not a meeting the service cannot find**
  - refused with {"detail":"meeting not found"} — 4xx here does not demonstrate a consent gate
- **the gate opens once consent is confirmed**
  - gate still reads "awaiting_confirmation" after a confirmation was accepted
- **the session starts once consent is confirmed**
  - status 404, {"detail":"meeting not found"}
- **the consent screen names the meeting it gates**
  - title reads "—"

## 03 — Catch a vague answer while it still matters

> Blocked: No Deepgram backend exists. `TranscriptionBackend` has three implementations in `core/crates/asr-live` and all three are fakes; the crate has no dependencies, so it cannot open a socket.

Video: `03-catch-a-vague-answer-live/journey.mp4` (58 frames). Screenshots: 1.

**Passed**

- the session stream is reachable
- the panel renders

**Failed**

- **the slow lane accepts a tick**
  - status 404, {"detail":"meeting not found"}
- **the panel shows live coverage from the session**
  - coverage chrome reads "— / —"
- **a follow-up question is surfaced to the operator**
  - nudge area reads "No active nudge"

## 04 — Run a meeting in two languages

> Blocked: Same missing vendor backend as journey 3 — the credential is configured and verified, but nothing can connect to Deepgram to transcribe.

Video: `04-run-a-code-switched-meeting/journey.mp4` (65 frames). Screenshots: 1.

**Passed**

- keyterm prompting is on, so client terms survive transcription
- a live transcription vendor is selected
- the selected speech vendor has a credential
- the speech vendor accepts the configured credential

**Failed**

- **the panel reports which languages are being heard**
  - language chrome reads "No language detected"

## 05 — When the connection drops

Video: `05-degraded-mode/journey.mp4` (61 frames). Screenshots: 1.

**Passed**

- the panel is not falsely claiming degraded mode while the model is reachable
- the configured model credential is reachable
- an egress audit trail is available

**Failed**

- **the audit records what left the machine**
  - audit returned [] after a live model call was made

## 06 — Check the recording

> Blocked: `app/modules/asr-record` makes no outbound HTTP call, so the record path has no vendor client to reconcile two engines with.

Video: `06-reconcile-the-recording/journey.mp4` (48 frames). Screenshots: 1.

**Passed**

- the record path accepts a transcription request

**Failed**

- **divergences between the two engines are reported**
  - status 404, {"detail":"record-path alignment not found"}
- **the screen names the engines that transcribed the meeting**
  - 0 engine rows rendered
- **the screen reports how far the engines agreed**
  - agreement reads "0%"

## 07 — Get the write-up

Video: `07-produce-the-debrief/journey.mp4` (393 frames). Screenshots: 5.

**Passed**

- a debrief conversation opens
- the conversation is anchored to a session
- the debrief accepts a free-text question
- the conversation opens from the screen
- the screen shows the question and an answer
- the debrief screen reports no error

**Failed**

- **the answer comes from the model rather than a stub echo**
  - the service replied {"session_id":"dc2590b143ea43c29dbbf9184482ca65","meeting_id":"meeting-8","conversation_ref":"conversation-dc2590b143ea43c29dbbf9184482ca65","status":"open","streaming_enabled":true,"length_cap":null,"latency_budget_seconds":null,"opened_at":"2026-08-20T03:22:47.735275Z","nudge_dispositions":[],"his
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
- **the answer on screen is a real answer, not the question echoed back**
  - Elicta replied "ack: Which requirements are still only inferred?"
- **every claim on the debrief screen carries its citation**
  - 0 cited claims rendered

## 08 — Carry what you learned forward

Video: `08-carry-state-forward/journey.mp4` (58 frames). Screenshots: 1.

**Passed**

- engagement state is readable
- a second meeting is created in the same engagement

**Failed**

- **open questions are carried forward to the next meeting**
  - state reads {"engagement_id":"eng-6","inherited_open_questions":[],"requirements_state":null}
- **the requirements state is readable**
  - status 404, {"detail":"requirements state not found"}
- **the second meeting inherits candidate questions**
  - inherited bank: {"meeting_id":"meeting-9","candidates":[],"generated_at":"2026-08-20T03:23:28.167799Z"}
- **the arc shows the meetings held so far**
  - 0 meetings on the timeline

## 09 — Judge whether the suggestions are any good

Video: `09-replay-and-tune-ranking/journey.mp4` (58 frames). Screenshots: 1.

**Passed**

- a replay run starts
- a rating is accepted
- the run reports the precision and embarrassment gates

**Failed**

- **the run reports its suggestions**
  - status 404, {"detail":"no replay run: run-3"}
- **the replay screen names the run it is showing**
  - run label reads "—"
- **the screen lists suggestions to rate**
  - 0 suggestions rendered

## 10 — Set up the services Elicta uses

Video: `10-configure-providers/journey.mp4` (470 frames). Screenshots: 8.

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

Video: `11-control-capture/journey.mp4` (39 frames). Screenshots: 1.

**Passed**

- the capture state is stated in words, not colour alone
- an unavailable audio backend is explained rather than left looking like a choice

**Failed**

- **the screen lists the audio sources it can record from**
  - 0 sources listed

- note — capture in a browser: pause control disabled: true; reason shown: "Audio capture is unavailable outside the desktop app, so nothing is being recorded."

## 12 — Get Elicta onto people’s machines

Video: `12-install-and-roll-out/journey.mp4` (39 frames). Screenshots: 1.

**Passed**

- the build identifies its version and platform
- the signing state is stated, and unknown is distinguished from unsigned

**Failed**

- **the OS permissions this build holds are listed**
  - 0 permission rows rendered
