# Judging Whether the Suggestions Are Any Good

Whether a suggestion was worth interrupting a meeting for is a judgement, not a
measurement. So it is made by a person, on real meetings — and it decides whether
a new version is allowed to ship.

This is for whoever is responsible for the tool across engagements, rather than
for the person running a meeting.

## Replay a real meeting

A recorded meeting is run through Elicta again, exactly as it happened. Nothing
is sent anywhere and nothing costs anything: it is replaying its own past
behaviour, which also means the result is repeatable.

You then rate what it suggested, on two separate scales.

```diagram
type: compare
title: Two ratings, deliberately not opposites
left: Useful
right: Embarrassing
item: The question it answers | Was this worth the interruption? | Would I have minded the client seeing it?
item: A suggestion can be | Useless without being humiliating | Humiliating regardless of how apt it was
item: What a bad score costs | A wasted moment | Trust you do not get back
```

They are kept apart on purpose. Combining them into a single score would let a
high usefulness rating average an embarrassment away, and an embarrassment is
not the kind of thing that should be averaged.

![A version that clears both bars](../../docs/journeys/screenshots/replay-passing.png)

## Two bars, and one of them is absolute

At least **70 per cent** of suggestions must be rated useful.

The number rated embarrassing must be **zero**. Not low — zero. One is enough to
hold a release.

![A version that fails both](../../docs/journeys/screenshots/replay-failing.png)

A version that fails either bar is blocked automatically. Nobody has to remember
to check.

## Where this is honest about itself

Replaying, recording ratings, both bars and the automatic block all work today.

Each bar now shows what it was measured over, which matters more than it sounds.
A figure of "useful nine times in ten" means one thing across four ratings and
quite another across four hundred, and the screen used to show only the
percentage — once reporting a comfortable pass, in green, from a single rating.
A run with nothing rated yet says so, rather than claiming either a pass or a
failure it has no grounds for.

What is missing is the way in. A run's individual suggestions are not yet listed
on the screen, so there is nowhere to sit and rate them; the ratings behind these
figures were recorded another way.

Both bars are judged separately for each language, so adding a language means
finding a fluent rater who also does business analysis — not just translating a
word list. That is worth planning for early, because it is a hiring problem
rather than a software one.

<!-- HANDBOOK-NAV -->

---

← [Carrying It Into the Next Meeting](32-the-next-meeting.md) · [Contents](../index.md) · [What It Will Not Do](41-what-it-will-not-do.md) →
