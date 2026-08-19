<!-- HANDBOOK-GENERATED: do not edit by hand -->
<!-- built from: docs/journeys -->

# What Works Today

> This page is assembled automatically every time this guide is made,
> from notes kept alongside the product itself, so it cannot fall out of date.
> Editing it by hand has no effect — the next build puts it back.

36 notes in total, 30 of them describing something that works today.

This page is read from the notes kept alongside each part of the product, so it says what is true now rather than what was true when somebody last remembered to update a page.

## Working today

You can rely on these.

| Part of the product | What the note says |
|---|---|
| Prepare for the engagement | Setting up the engagement, tagging and indexing documents, the client vocabulary list, and reviewing and pruning the question bank |
| Start the meeting | The consent gate, the record of who confirmed, and the whole audio-handling policy including automatic destruction |
| Start the meeting | The desktop app now opens a real microphone. It offers the audio interface and the silent-join capture path, warns you off the room mic, and releases the device when you stop |
| Start the meeting | Elicta will join meetings as a silent participant through a single meeting-bot service that covers every platform, rather than integrating with Zoom, Teams and Meet separately. That keeps one integration instead of three, and gives us who-said-what as a fact the platform reports rather than something guessed from the audio. The connection point is built and tested; the vendor contract is a commercial step, not an engineering one |
| Catch a vague answer while it still matters | The whole panel, all four responses, the running coverage count, and the live connection that feeds suggestions to it |
| Catch a vague answer while it still matters | Your taps are sent back, so the debrief knows which suggestions you used and which you set aside |
| Catch a vague answer while it still matters | The microphone is connected. The desktop app opens the device, and audio flows through to the suggestions on this screen |
| Run a meeting in two languages | Detecting and displaying both languages, keeping the suggestion and the interface in different languages, and number conversion |
| Run a meeting in two languages | The Mandarin list now covers the phrasings that carry evasion in Chinese business speech — including the deferrals that sound like agreement and are not, such as “we'll look into it”, and the qualifiers that quietly withdraw most of a yes |
| Run a meeting in two languages | We measured it rather than leaving it open. The two languages do not cover the same ground, and that is correct: Mandarin catches a whole category of deferred commitment that English carries in tone rather than words, so no word list could find it. Each language is stronger than the other somewhere, and the gaps are now named rather than assumed away |
| When the connection drops | The two-speed design, the panel's degraded state, and honest recording of what could not be completed |
| When the connection drops | The panel is now told which mode it is in by the live connection itself, before it shows you a single suggestion — so a quiet panel is never ambiguous between “nothing to say” and “the model is unreachable” |
| Check the recording | Running both transcribers, comparing them, flagging every disagreement, and the automatic destruction of the audio |
| Check the recording | The check for that is now built: given a recording and a correct transcript, it reports what share of the mistakes the pairing would actually have shown you. A sample containing no mistakes reports “cannot tell” rather than a clean pass, because it is no evidence either way |
| Get the write-up | The whole sequence — cleaning up the transcript, translating while keeping the original, sorting statements into template sections, drafting the documents, and attaching every source |
| Get the write-up | If any step fails, the sequence stops there and says so, rather than passing invented material to the next step |
| Get the write-up | Asking follow-up questions in your own words now has a screen. You can query the meeting, ask for a paragraph to be drafted, and every answer names the moment it rests on |
| Carry what you learned into the next meeting | Carrying requirements, decisions and open questions across meetings, and weighting the next meeting's questions toward what is unresolved |
| Carry what you learned into the next meeting | All of it now survives restarting the service. The client, its meetings, the open questions, the standing requirements and the prepared question bank are written to a database as they change, and read back when Elicta next starts |
| Carry what you learned into the next meeting | Only the five things above are stored. The working notes a debrief produces along the way are rebuilt from the recording rather than kept — slower, but a stored copy could go stale against the recording it came from, and a stale one is worse than none |
| Judge whether the suggestions are any good | Replaying meetings, rating suggestions, both quality bars, and automatic blocking of a release that fails either |
| Judge whether the suggestions are any good | The starting weights are now chosen rather than left at a placeholder, and the reasoning is written down: say less, more confidently, because a suggestion that misfires in front of a client costs more than one that never fires. A question you have already asked can never be suggested again ahead of one you have not — that is guaranteed by the numbers themselves, not left to chance |
| Set up the services Elicta uses | Everything on this screen, including live credential testing for the AI provider and both supported transcription services |
| Set up the services Elicta uses | For a shared deployment the key can now come from your own secret store — 1Password, Vault, AWS, Google, anything with a command line. If the store cannot be reached, Elicta refuses to start and says why, rather than quietly making a new key that leaves the other machines unable to read anything |
| Control the recording while the meeting runs | The whole screen — pause and resume, the state display, the input warning, and voice enrolment |
| Control the recording while the meeting runs | Pause now pauses a real microphone. Audio captured while paused is discarded rather than held back, and resuming is instant because the device is never closed |
| Get Elicta onto people's machines | Packaging for both platforms, signing and verification, the managed-deployment profile, and the automatic check that both platforms behave identically |
| Get Elicta onto people's machines | The About screen reports the real version and platform it is running on |
| Get Elicta onto people's machines | Whether the build is signed, and how it was installed, are now read from the operating system rather than taken on trust. Where the answer cannot be established the screen says so, which reads differently from “unsigned” — an IT reviewer needs to tell those apart |
| Get Elicta onto people's machines | Elicta checks for a new version on launch and tells you what is waiting. It never installs on its own — an update that restarted the app by itself would eventually do it during a client meeting |

## Needs setting up first

These work, once somebody has configured the outside service they depend on.

| Part of the product | What the note says |
|---|---|
| Prepare for the engagement | Drafting the questions needs an AI provider configured in Settings — a one-off step covered in journey 10. Until then the screen works and the bank stays empty |

## Still to come

These are described elsewhere in this guide as things that are not finished. They are listed together here so that nobody has to hunt for the caveats.

| Part of the product | What the note says |
|---|---|
| Run a meeting in two languages | A bilingual business analyst still needs to review that list against real client recordings before we would rely on it. Building it was the long part; checking it is the part we cannot do without a native speaker who does this work |
| Check the recording | The check still has to be run against real client recordings. We can measure the answer now; we do not have it yet |
| Get the write-up | Needs an AI provider with capacity. The connection has been tested against the live service and works; the account used for testing was rate limited, so a complete run has not been produced yet |
| Judge whether the suggestions are any good | Both bars are judged per language, so adding a language means finding a fluent rater with business-analysis experience — not just translating a word list. Worth planning for early |
| Get Elicta onto people's machines | The update service needs its signing key and address set before a release goes out. Until then the screen says there is no update channel configured, rather than accepting whatever it is offered |

<!-- HANDBOOK-NAV -->

---

← [What It Will Not Do](41-what-it-will-not-do.md) · [Contents](../index.md)
