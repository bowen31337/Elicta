# Running a Meeting in Two Languages

A bilingual meeting is not an English meeting with a few foreign words in it.
Requirements arrive in both languages, and the vague answer you need to chase is
as likely to be in one as the other.

## Both languages, visibly

The panel shows which languages it is hearing, and how well it supports each one.

![A suggestion in a meeting running in two languages](../../docs/journeys/screenshots/panel-code-switched.png)

That is not decoration. Support varies by language, and you should be able to see
at a glance whether a quiet panel means "nothing worth asking" or "I am on
unfamiliar ground here."

## The suggestion is in the room's language; everything else is in yours

The question you might read aloud appears in the language the meeting is being
held in. The short version, the reason it fired, and every label around it stay
in yours — and you set that separately.

The person reading the panel and the person being asked the question are not the
same person, so they do not get the same language.

## Numbers

A spoken figure has to reach you as a figure you can act on: three hundred and
fifty myriad has to arrive as **3,500,000**, not as words.

No transcription service handles that reliably, so Elicta converts numbers itself
and is tested on it in each language.

This sounds like a detail and is not. A question about volume whose answer is
captured at the wrong order of magnitude is worse than never asking — you would
walk away believing you had a number.

## Where this is honest about itself

Detecting both languages, keeping the panel and the suggestion in different
languages, and converting numbers all work today.

The list of phrasings that carry evasion in Mandarin has been built — including
the deferrals that sound like agreement and are not — but a bilingual business
analyst still needs to check it against real client recordings before anyone
should lean on it. Building the list was the long part; checking it needs a
native speaker who does this work.

One thing worth knowing: the two languages deliberately do not cover the same
ground. Mandarin catches a category of deferred commitment that English carries
in tone rather than in words, which no word list could find. Each language is
stronger than the other somewhere, and those gaps are named rather than assumed
away.

<!-- HANDBOOK-NAV -->

---

← [Controlling the Recording](21-controlling-the-recording.md) · [Contents](../index.md) · [When the Connection Drops](23-when-the-connection-drops.md) →
