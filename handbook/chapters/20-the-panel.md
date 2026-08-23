# The Panel and the Suggestion

This is what Elicta is for. A client says something that sounds like an answer
but is not one, and five seconds later you ask the question that pins it down —
instead of thinking of it in the car afterwards.

Two things to know before the rest of this chapter describes it. What the
microphone hears is now turned into words while the meeting runs, checked for
the kind of vagueness that costs a requirement, and a question is put in front
of you — so what follows describes what you will actually see, not what the
screen would do if something reached it.

The checks that raise a question are the ones about wording: an amount with no
number, an adjective with no threshold, a date that is not a date, a commitment
behind a hedge. Those need no model and are quick enough to land while the
sentence is still in the air. Three other ways a question could be earned are
not built yet — an action with nobody named as doing it, an answer that
contradicts a document you supplied, and a system or team nobody has mentioned
before — so a meeting can pass without a suggestion and that is the product
being quiet rather than broken.

## Before anyone speaks

The panel shows how much of your template is covered, how long is left, and
which languages it is listening for — worked out from what you told it about the
client, so nobody has to pick one before the meeting starts. There is no
suggestion, because nobody has said anything yet.

![The panel before the meeting starts](../../docs/journeys/screenshots/panel-before-meeting.png)

A near-empty panel is the correct resting state. Anything more would pull your
eyes to a screen during the part of the meeting where you are establishing
rapport.

## Something vague lands

The client says *"the dashboard has to be fast."* That is not a requirement, it
is a feeling. Elicta recognises it and puts one question in front of you.

![A suggested question, and why it fired](../../docs/journeys/screenshots/panel-nudge-surfaced.png)

Three things, in the order you need them:

```diagram
type: stack
title: What is on a suggestion, and why
item: The short version | Readable at a glance, without breaking eye contact.
item: The full question | The exact wording, if you want to ask it word for word.
item: Why it fired | Quietly underneath. This matters more than it looks — it is how you tell in half a second whether Elicta understood the room or misheard it, and therefore whether to trust the next one.
```

Only one suggestion is shown at a time. Earlier ones move below a line and fade
back — still readable if you want them, never competing with the current one.

## You answer in one tap

You have one hand and no attention, so every response is a single tap.

```diagram
type: compare
title: The four responses
left: What you tap
right: What it means
item: You covered that topic | Asked it | The section fills in immediately
item: Fair question, wrong moment | Park it | It is kept for the write-up
item: That answer opened something | Go deeper | It follows the thread
item: Show me the biggest hole | What am I missing? | It names the most urgent uncovered topic
```

Tapping *Asked it* fills the section in front of you straight away, rather than
waiting for anything to confirm. Your confirmation is what you can see.

![Coverage moves the moment you tap](../../docs/journeys/screenshots/panel-asked-it.png)

## The way out

There is also a text box at the bottom for typing your own question. It is
deliberately the quietest thing on the screen — a way out, not the way to work.

It exists because a tool that only accepts the four answers it expected will
eventually be wrong in a way nobody can tell it about.

<!-- HANDBOOK-NAV -->

---

← [Starting a Meeting](11-starting-a-meeting.md) · [Contents](../index.md) · [Controlling the Recording](21-controlling-the-recording.md) →
