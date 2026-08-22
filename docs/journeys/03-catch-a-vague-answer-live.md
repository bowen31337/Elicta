# 3. Catch a vague answer while it still matters

*For the person running the meeting · during it*

This is what Elicta is for. A client says something that sounds like an answer
but is not one, and five seconds later you ask the question that pins it down —
instead of thinking of it in the car afterwards.

## Before anyone speaks

The panel shows how much of your template is covered and how long is left, and
nothing else. There is no suggestion because nobody has said anything yet.

An empty panel is the right resting state. Anything shown here would pull your
eyes to a screen during the part of the meeting where you are establishing
rapport.

![The panel before the meeting starts](screenshots/panel-before-meeting.png)

## Something vague lands

The client says *"the dashboard has to be fast."* That is not a requirement —
it is a feeling. Elicta recognises it and puts one question in front of you.

Three things, in the order you need them: a short version you can read at a
glance without breaking eye contact, the full question if you want to ask it
word for word, and — quietly underneath — why it fired. That last line matters
more than it looks. It is how you tell in half a second whether Elicta
understood the room or misheard it, and whether to trust the next one.

![A suggested question, and why it fired](screenshots/panel-nudge-surfaced.png)

Only one suggestion is ever shown at a time. Earlier ones move below a line and
fade back, still readable if you want them, never competing with the current
one.

## You answer in one tap

You have one hand and no attention, so every response is a single tap:

- **Asked it** — I covered that. The section fills in immediately.
- **Park it** — not now; keep it for the debrief.
- **What am I missing?** — show me the most urgent thing not yet covered.
- **Go deeper** — that answer opened something; follow it.

Tapping *Asked it* fills the section in front of you straight away rather than
waiting for anything to confirm. Your confirmation is what you can see, not a
round trip you would never notice.

![Coverage moves the moment you tap](screenshots/panel-asked-it.png)

There is also a text box at the bottom for typing your own question. It is
deliberately the quietest thing on the screen — a way out, not the way to work.

## Where this stands

| | |
|---|---|
| ✅ Ready | The panel itself: the running coverage count and time remaining, the suggestion and the line saying why it fired, all four one-tap responses, and the box for typing your own. It is connected to the meeting's live session, so whatever that session sends appears here |
| ✅ Ready | Your taps are recorded against the meeting and sent back, so the debrief knows which suggestions you used and which you set aside |
| ✅ Ready | The microphone. The desktop app opens the device, offers the audio interface and the silent-join path, and releases it when you stop |
| ⏳ Not yet | Anything to put in the panel. Nothing turns speech into words yet: the connection point for a transcription service has three implementations and all three are stand-ins used for testing, so no sentence is ever produced, nothing is ever recognised as vague, and no suggestion is ever raised. Everything above this line works and has been tested; during a real meeting the panel would sit at its resting state all the way through |
