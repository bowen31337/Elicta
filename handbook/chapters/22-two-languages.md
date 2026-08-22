# Running a Meeting in Two Languages

A bilingual meeting is not an English meeting with a few foreign words in it.
Requirements arrive in both languages, and the vague answer you need to chase is
as likely to be in one as the other.

## Both languages, visibly

The panel shows which languages are in play, and how well it supports each one.

Two different things put a language there, and the panel says which. One it is
**listening for**, worked out from what you told it about the client — a
Shenzhen depot team implies Mandarin before anybody speaks. One it has **heard**
is a language the transcription actually found. An expectation is drawn as an
expectation; only a language actually heard carries a support badge, because
support is measured from what was said and there is nothing to measure until
something is.

![A suggestion in a meeting running in two languages](../../docs/journeys/screenshots/panel-code-switched.png)

That is not decoration. Support varies by language, and you should be able to see
at a glance whether a quiet panel means "nothing worth asking" or "I am on
unfamiliar ground here."

## The suggestion should be in the room's language; everything else in yours

This is the intent rather than today's behaviour, and it is worth knowing which.

The question you might read aloud should appear in the language the meeting is
being held in. The short version, the reason it fired, and every label around it
should stay in yours, set separately. The person reading the panel and the person
being asked the question are not the same person, so they should not get the
same language — a panel that assumes otherwise makes one of them work in a
second language while concentrating on a client.

Today there is no setting for the language you read, and a suggestion carries no
language of its own, so both are whatever the screen is written in.

## Numbers

A spoken figure has to reach you as a figure you can act on: three hundred and
fifty myriad has to arrive as **3,500,000**, not as words.

No transcription service handles that reliably, so Elicta converts numbers itself
rather than trusting one. That conversion is written and tested in each language
— and not yet connected to anything, because the transcript it would convert
does not arrive yet.

This sounds like a detail and is not. A question about volume whose answer is
captured at the wrong order of magnitude is worse than never asking — you would
walk away believing you had a number.

## Where this is honest about itself

What works today is the panel saying which languages are in play, and telling
apart the ones it is listening for from the ones it has heard.

What does not is everything that depends on hearing them. Elicta has no
connection to a transcription service yet, so nothing is transcribed, so no
language is ever *heard*, no number is ever converted, and no phrasing is ever
matched. All of that is built and waiting on one missing piece; none of it is
reaching you.

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
