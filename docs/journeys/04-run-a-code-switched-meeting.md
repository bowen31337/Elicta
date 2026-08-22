# 4. Run a meeting in two languages

*For the person running the meeting · when the room switches between languages*

A bilingual meeting is not an English meeting with a few foreign words in it.
Requirements arrive in both languages, and the vague answer you need to chase
is as likely to be in one as the other.

## Both languages, visibly

The panel shows which languages are in play, and how well it supports them.
That is not decoration: support varies by language, and you should be able to
see at a glance whether the quiet panel means "nothing to ask" or "I am on
unfamiliar ground here."

Two different things can put a language on that strip, and it says which. A
language Elicta is **listening for** comes from what you told it about the
client — a Shenzhen depot team implies Mandarin before anyone speaks. A language
it has **heard** is one the transcription actually found. The first is an
expectation and is drawn as one; only the second carries a support badge,
because support is measured per observation and there is nothing to measure
until something is said.

![A suggestion in a meeting running in two languages](screenshots/panel-code-switched.png)

## The suggestion should be in the meeting's language; everything else in yours

This one is the intent, not yet the behaviour, and it is worth stating because
it shapes what gets built next.

The question you might read aloud should appear in the language the meeting is
being held in. The short version, the reason it fired, and every label around it
should stay in yours — set independently. The person reading the panel and the
person being asked the question are not the same person, and a panel that
assumes they are makes one of them work in a second language while
concentrating.

Today there is no setting for the language you read, and a suggestion carries no
language of its own, so both are whatever the screen is written in.

## The number problem

`三百五十万` has to reach you as **3,500,000**. No transcription service handles
that reliably, so Elicta does the conversion itself rather than trusting one —
written and tested per language, and not yet connected to anything, because the
transcript it would convert does not arrive yet.

This sounds like a detail and is not. A question about volume whose answer gets
captured at the wrong order of magnitude is worse than never asking — you would
walk away believing you had a number.

## Where this stands

| | |
|---|---|
| ✅ Ready | Showing which languages are in play, and telling apart the ones Elicta is listening for from the ones it has heard. What it listens for is worked out from the client background when the engagement is made, kept with the engagement, and shown on the panel before a word is spoken |
| ⏳ Not yet | **Hearing them.** Detection needs a transcription service, and no client for one exists on the live path — so today the strip shows what is expected and never fills in what was heard. Everything downstream of detection is built and waiting on that one piece |
| ⏳ Not yet | **The suggestion in one language and the interface in another.** There is no setting for the language you read, and a suggestion carries no language of its own, so today both are whatever the screen is written in |
| ⏳ Not yet | **Number conversion, in the product.** It is written and tested — thoroughly, per language — but it lives in a component nothing calls yet, so no number reaching you has been through it |
| ⏳ Not yet | Nothing reaches the Mandarin list yet, for the same reason as the rest of this page: it is read from a transcript, and nothing is transcribing. The list itself covers the phrasings that carry evasion in Chinese business speech — including the deferrals that sound like agreement and are not, such as “we'll look into it”, and the qualifiers that quietly withdraw most of a yes |
| ⏳ Not yet | A bilingual business analyst still needs to review that list against real client recordings before we would rely on it. Building it was the long part; checking it is the part we cannot do without a native speaker who does this work |
| ✅ Answered | We measured it rather than leaving it open. The two languages do not cover the same ground, and that is correct: Mandarin catches a whole category of deferred commitment that English carries in tone rather than words, so no word list could find it. Each language is stronger than the other somewhere, and the gaps are now named rather than assumed away |
