# 11. Control the recording while the meeting runs

*For the person running the meeting · during it*

Two controls here are safety features rather than conveniences, and they shape
everything about the screen.

## Pause is one tap, and always in the same place

You reach for pause when a client says *"can we take this bit off the record."*
A control that needs hunting for — or that asks whether you are sure — fails at
exactly that moment. So it runs the full width of the screen, never moves, and
takes effect immediately. There is no buffered audio still on its way.

![Recording, with pause one tap away](screenshots/capture-recording.png)

## You can tell what state it is in without reading carefully

Believing you are paused while still recording is the worst thing this product
could do to you. So the state is said three ways at once — the word, the
sentence under it, and the colour — and never by colour alone, which also means
it works if you cannot distinguish those colours.

![Paused, and saying so unmistakably](screenshots/capture-paused.png)

## It argues for the better microphone

Elicta does not just accept whatever audio it is given. Wired input, or a
silent join, is markedly more accurate than a microphone in the middle of a
table — people talking over each other is a bigger source of error than the
choice of transcription service.

So a room microphone gets a warning that stays on screen, rather than a dialog
at the start that everyone dismisses.

![On a room microphone, with the warning that earns its place](screenshots/capture-acoustic-warning.png)

## Your own voice

You can record up to a minute of yourself so Elicta can tell your speech from
the client's. Without it, a question *you* asked can be recorded as something
the client wanted — and that error carries all the way into the write-up.

You choose which microphone to record it from, separately from the input the
meeting is being recorded on. Those are different jobs: the meeting wants the
cleanest feed of the room, and this wants whatever is closest to your own mouth
— often a headset the meeting is not running through at all.

The recording is counted out loud while it runs and stops itself at a minute.
What is kept is a small numerical description of your voice; the recording
itself is never stored. You can re-record whenever you like, and each one
replaces the last.

## Where this stands

| | |
|---|---|
| ✅ Ready | Pause and resume, the state display, and the input warning |
| ✅ Ready | Pause now pauses a real microphone. Audio captured while paused is discarded rather than held back, and resuming is instant because the device is never closed |
| ✅ Ready | **A control that cannot work now says why.** A live run photographed a greyed-out "Start recording" beside an empty input list, with no explanation anywhere on the screen — the page was secure and the browser offered microphone access, so both existing checks passed and the screen concluded there was nothing to explain. The machine simply had no microphone. That case now says so, because an operator can act on "no microphone" and can do nothing at all about a dead button |
| ✅ Ready | **A check before the meeting, and a choice of input.** Check microphone opens the chosen input, shows a live level and records nothing — which is also what makes a browser reveal the real names of its microphones, since it withholds ids and labels until the first permission grant and the picker before that reads "Microphone 1". The checked device is promoted to recording rather than reopened, so there is no second prompt and no gap. It matters that the choice is made here: capture refuses a second session on either backend, so swapping input mid-meeting means stopping and restarting |
| ✅ Ready | **Starting a recording is what books the meeting.** The consent screen used to carry a Start button that registered a session and opened no microphone, so an operator was told a meeting had begun while nothing was listening — and it offered no way to pick an input, being a screen that cannot show one working. Both moved here. The device is opened before the meeting is registered, so an input that will not open books nothing |
| ✅ Ready | **Recording your own voice.** The button used to do nothing, and the words above it said "Not enrolled" however many times you had enrolled — there was no route behind it to enrol against. Recording now works: up to a minute, counted out loud as it runs, capped by the service rather than by the screen, and the recording itself is turned into a voiceprint and thrown away rather than stored. During a meeting your own sentences are no longer interrogated as though a client had said them |
| ⏳ Not yet | **Telling two similar voices apart.** What compares voices is a baseline built from the shape of a voice, not the learned speaker model the design asks for — nothing in the product could run one, and adding it is its own piece of work. It separates voices that sound clearly different and may not separate two that sound alike. It leans towards treating speech as the client's when it is unsure, so the cost of being wrong is one question you did not need rather than a client requirement silently passed over. The screen says all of this where you enrol |
