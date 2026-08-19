# 2. Start the meeting

*For the person running the meeting · the first minute*

Recording a client without a clear record of their consent is the kind of
mistake that ends an engagement. So it is a gate you pass, not a warning you
read past.

## Consent first

Elicta shows how consent works for this client — agreed once for the whole
engagement, or needed for every meeting — and whether it has actually been
given. Until someone confirms it on the record, recording cannot start. The
button is simply unavailable.

![Consent not yet confirmed — recording cannot start](screenshots/consent-pending.png)

Once confirmed, the screen keeps who confirmed it and when, so the answer to
"did we have permission for this?" is never a memory test.

![Consent confirmed, and recording can begin](screenshots/consent-confirmed.png)

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
| ✅ Ready | The consent gate, the record of who confirmed, and the whole audio-handling policy including automatic destruction |
| ✅ Ready | The desktop app now opens a real microphone. It offers the audio interface and the silent-join capture path, warns you off the room mic, and releases the device when you stop |
| ✅ Decided | Elicta will join meetings as a silent participant through a single meeting-bot service that covers every platform, rather than integrating with Zoom, Teams and Meet separately. That keeps one integration instead of three, and gives us who-said-what as a fact the platform reports rather than something guessed from the audio. The connection point is built and tested; the vendor contract is a commercial step, not an engineering one |
