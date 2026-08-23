# Controlling the Recording

Two of the controls on this screen are safety features rather than conveniences,
and that shapes everything about how it looks.

## Pause is one tap, and always in the same place

You reach for pause when a client says *"can we take this bit off the record."*
A control that needs hunting for — or that asks whether you are sure — fails at
exactly that moment.

So it is the largest control on the screen, never moves, and takes effect
immediately. There is no buffered audio still on its way. Stopping sits beside
it, deliberately smaller: stopping ends the meeting's recording and hands the
microphone back, and it is not the thing you want under your thumb when you
meant to pause.

![Recording, with pause one tap away](../../docs/journeys/screenshots/capture-recording.png)

## You can tell the state without reading carefully

Believing you are paused while still recording is the worst thing this product
could do to you.

So the state is said three ways at once — the word, the sentence under it, and
the colour — and never by colour alone, which also means it works for anyone who
cannot distinguish those colours.

![Paused, and saying so unmistakably](../../docs/journeys/screenshots/capture-paused.png)

Audio captured while paused is discarded rather than held back, and resuming is
instant because the microphone is never actually closed.

## Starting, and choosing what to listen to

Before anything is recording, the screen offers the inputs it can see and two
controls: one to check a microphone, and one to start recording. Where there is
more than one input, you pick which before you start rather than discovering
afterwards that it took the wrong one.

Checking opens the input and shows you the level moving, and records nothing.
It is worth doing every time. A muted or unplugged microphone produces a screen
that looks exactly like a working one, and without a level to watch the failure
only surfaces in the transcript, long after the meeting.

Take the choice seriously at this point, because it sticks: once a recording is
running the input cannot be swapped. Changing it means stopping and starting
again, and that leaves a hole in the recording.

Running Elicta in a web browser rather than as an installed application, the
microphone is the browser's to give, and browsers only hand it over on a secure
page. On an address that is not secure, the screen says so plainly rather than
claiming the feature is missing — the difference matters, because that one is
yours to fix and takes a moment.

The browser also asks your permission the first time, and it asks when you press
the button to check rather than the moment the screen opens. Until you have
allowed it, the browser will not tell Elicta the names of your microphones, so
the list shows a single unnamed input; allow it once and the real names, and any
other inputs, appear from then on. That is the practical reason the check exists
as its own step — it is what turns the list into a choice.

Starting the recording is also what registers the meeting. The input is opened
first, so if it cannot be opened, no meeting is registered at all and you are
free to fix the problem and try again. If you were already checking a
microphone, that is the one that records, with no second permission prompt and
no gap.

## It will argue for a better microphone

Elicta does not simply accept whatever audio it is given. A wired input, or
joining the call as a silent participant, is markedly more accurate than a
microphone in the middle of a table. People talking over each other causes more
transcription errors than the choice of transcription service does.

So a room microphone earns a warning that stays on screen, rather than a dialog
at the start that everyone dismisses without reading.

![On a room microphone, with the warning that earns its place](../../docs/journeys/screenshots/capture-acoustic-warning.png)

## Record your own voice once

The idea is that you record up to a minute of yourself so that Elicta can tell
your speech from the client's.

It would be worth the minute. Without it, a question *you* asked can be recorded
as something the client wanted — and that error carries all the way into the
write-up, where nobody would know to doubt it.

## Where this is honest about itself

Pausing, the state display and the argument for a better microphone all work,
and they work in the installed app rather than only in principle.

Recording your own voice does not. The screen offers it and the button does
nothing yet, so today every voice in the room is treated the same way — which
is the error described above, still waiting to be prevented.

Capture no longer needs the installed application. In a browser on a secure
page, the page's own microphone is used and the browser's recording indicator
stays lit throughout, so the room can see the recording is running. What the
installed application still has to itself is everything the browser cannot
reach: the wired inputs and the silent join.

Where recording cannot start, the screen says which of the reasons it is — the
page is not secure, the browser offers no microphone access, or the machine has
no microphone attached — and disables the controls rather than sitting there
looking ready. That last one was found the hard way: the controls went grey on
a perfectly ordinary page and nothing on the screen accounted for it.

<!-- HANDBOOK-NAV -->

---

← [The Panel and the Suggestion](20-the-panel.md) · [Contents](../index.md) · [Running a Meeting in Two Languages](22-two-languages.md) →
