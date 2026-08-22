# When the Connection Drops

Networks fail in client offices. Elicta is built so that when the part of it that
needs the internet cannot be reached, the meeting does not stop — it just gets
quieter.

## What keeps working

The fastest and most valuable suggestions never needed the internet at all.

Spotting an unquantified word like *fast* is a matter of matching against a list
prepared in advance, so losing the connection does not touch it. Coverage
tracking and every button on the panel are local in the same way.

What pauses is the slower, cleverer layer: noticing that an answer contradicts
something said twenty minutes ago, or that a system just mentioned appears
nowhere in the briefing pack.

```diagram
type: compare
title: What you lose, and what you keep
left: Still working
right: Paused
item: Vague words like "fast" or "a few" | Yes | —
item: Topics you have not covered yet | Yes | —
item: All four one-tap responses | Yes | —
item: Contradicting something said earlier | — | Paused
item: Spotting a system nobody briefed you on | — | Paused
```

## You are told, not left to guess

![The panel says plainly that it is running on the fast path only](../../docs/journeys/screenshots/panel-degraded.png)

The panel says which mode it is in and what that means, and it is told before it
shows you a single suggestion. The alternative — going quiet and letting you
assume there was nothing worth asking — is the one behaviour that would genuinely
mislead you.

What it says is read from what actually happened when Elicta last spoke to the
service it depends on, rather than from whether that service was set up. Those
are different questions, and only the first one changes during a meeting.

It also names which problem it met, because they do not have the same fix:

```diagram
type: stack
title: Four ways the clever half goes quiet
item: The service cannot be reached | Usually the network in this room. Nothing to change; it comes back when the connection does.
item: The service is throttling you | Nothing is wrong and nothing is misconfigured. It clears on its own.
item: Your key was refused | Re-enter it in Settings. Waiting will not help.
item: Your plan does not cover it | The plan or the permission is the thing to change, not the key.
```

A service nobody has needed yet is reported as fine rather than as broken —
most meetings never call on the slower half, and a warning shown on all of them
is a warning you stop reading. When it starts working again the panel says so
without anything being restarted.

## The write-up says what it could not do

Nothing is invented while the connection is down. The write-up is produced in
stages, and a stage that cannot reach the service stops there rather than
guessing at the rest.

That leaves you with a shorter write-up, which on its own looks exactly like a
meeting where little was decided. So the debrief screen tells you which stage
stopped and what it reported, and you can read the rest knowing what is missing
and why.

<!-- HANDBOOK-NAV -->

---

← [Running a Meeting in Two Languages](22-two-languages.md) · [Contents](../index.md) · [Checking the Recording](30-checking-the-recording.md) →
