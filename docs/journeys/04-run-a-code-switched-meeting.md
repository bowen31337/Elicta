# 4. Run a meeting in two languages

*For the person running the meeting · when the room switches between languages*

A bilingual meeting is not an English meeting with a few foreign words in it.
Requirements arrive in both languages, and the vague answer you need to chase
is as likely to be in one as the other.

## Both languages, visibly

The panel shows which languages it is hearing, and how well it supports them.
That is not decoration: support varies by language, and you should be able to
see at a glance whether the quiet panel means "nothing to ask" or "I am on
unfamiliar ground here."

![A suggestion in a meeting running in two languages](screenshots/panel-code-switched.png)

## The suggestion is in the meeting's language; everything else is in yours

The question you might read aloud appears in the language the meeting is being
held in. The short version, the reason it fired, and every label around it stay
in yours — and you set that independently. The person reading the panel and the
person being asked the question are not the same person.

## The number problem

`三百五十万` has to reach you as **3,500,000**. No transcription service handles
that reliably, so Elicta does the conversion itself and is tested on it
per language.

This sounds like a detail and is not. A question about volume whose answer gets
captured at the wrong order of magnitude is worse than never asking — you would
walk away believing you had a number.

## Where this stands

| | |
|---|---|
| ✅ Ready | Detecting and displaying both languages, keeping the suggestion and the interface in different languages, and number conversion |
| ✅ Ready | The Mandarin list now covers the phrasings that carry evasion in Chinese business speech — including the deferrals that sound like agreement and are not, such as “we'll look into it”, and the qualifiers that quietly withdraw most of a yes |
| ⏳ Not yet | A bilingual business analyst still needs to review that list against real client recordings before we would rely on it. Building it was the long part; checking it is the part we cannot do without a native speaker who does this work |
| ✅ Answered | We measured it rather than leaving it open. The two languages do not cover the same ground, and that is correct: Mandarin catches a whole category of deferred commitment that English carries in tone rather than words, so no word list could find it. Each language is stronger than the other somewhere, and the gaps are now named rather than assumed away |
