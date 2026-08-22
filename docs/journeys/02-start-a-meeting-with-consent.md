# 2. Start the meeting

*For the person running the meeting · the first minute*

Recording a client without a clear record of their consent is the kind of
mistake that ends an engagement. Elicta has a gate for exactly that — and in
this build, the gate is set not to ask.

## Consent, and what this build actually does

As it ships today, no meeting stops to ask. Every engagement is treated as
having settled consent once, for the engagement as a whole, so recording can
start straight away and nothing is written down about who agreed to it.

The screen is careful about the difference between not asking and having an
answer: it reports that nothing is recorded here rather than showing a
reassuring tick.

![Consent is not being asked for, and nothing is on record](screenshots/consent-not-asked.png)

That is a setting for this stage, not an oversight. It means having the consent
conversation, and being able to show later that you had it, rests with the
person running the meeting rather than with the software.

## The gate, where an engagement asks at every meeting

The gate itself is built and works. Where an engagement is set to ask,
recording cannot start until someone confirms it on the record — the button is
simply unavailable.

![Consent not yet confirmed — recording cannot start](screenshots/consent-pending.png)

Confirming happens on this screen. Elicta sets out what has to be true before
recording — that everyone has been told and has agreed — with the law that
rests on, and asks who is confirming it. That name is not a participant list:
it records who is accountable for having disclosed the recording.

Once confirmed, the screen keeps who confirmed it and when, so the answer to
"did we have permission for this?" is never a memory test.

![Consent confirmed, and recording can begin](screenshots/consent-confirmed.png)

Nothing can switch an engagement over to asking yet, so for now every
engagement takes the setting described above.

## What happens to the recording, said before it happens

The same screen tells you what Elicta will do with the audio, before a second
of it exists:

- It is never written to disk. It lives in memory only while it is being
  transcribed.
- The moment transcription and speaker identification finish, it is destroyed —
  and the deletion itself is recorded, so the destruction can be shown rather
  than asserted.
- Every transcription request tells the vendor not to keep a copy. Your contract
  may already say that; sending it with each request is what makes it something
  an audit can verify.

## Where this stands

| | |
|---|---|
| ✅ Ready | The whole audio-handling policy, including automatic destruction, and — wherever an engagement asks for consent — the gate that holds recording shut and the record of who confirmed it |
| ⏳ Not yet | Asking for consent at all. Every engagement is currently set to treat consent as settled for the engagement as a whole, so no meeting asks and no consent record is written. The gate that would ask is built and tested; nothing can switch an engagement over to it yet |
| ✅ Ready | The desktop app now opens a real microphone. It offers the audio interface and the silent-join capture path, warns you off the room mic, and releases the device when you stop |
| ✅ Decided | Elicta will join meetings as a silent participant through a single meeting-bot service that covers every platform, rather than integrating with Zoom, Teams and Meet separately. That keeps one integration instead of three, and gives us who-said-what as a fact the platform reports rather than something guessed from the audio. The connection point is built and tested; the vendor contract is a commercial step, not an engineering one |
