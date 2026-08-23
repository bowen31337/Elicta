# 1. Prepare for the engagement

*For the person running the meetings · days before the first one*

Almost everything that makes Elicta useful happens before anyone sits down. The
thinking is done in advance so that the meeting itself only has to pick the
right question from work already finished — which is the only way a suggestion
can arrive while it is still useful.

## Tell it about the client

Elicta opens on your clients: a list of the engagements you have, and the place
to add one. You give it the basics — who the client is, the sector, and the
commercial shape of the engagement. That is not filing; it is what lets Elicta
work out which languages to expect in the room, so nobody has to be asked to
choose one before a meeting starts.

![Your clients: the engagements you have, and the form for adding one](screenshots/engagements-list.png)

Opening one is what makes it the client every other screen is about, and that
choice follows you through the rest of this journey. Everything below happens
on the Preparation screen, about the one client you opened.

## Set up the meetings it will have

An engagement is a client; a meeting is one conversation with them. Everything
after this page — consent, the live panel, the recording, the write-up — is
about a meeting, so the engagement needs at least one before any of it applies.

Adding one asks a single question: how the audio will reach Elicta. Line-in
from the meeting machine, a silent join that takes the audio as loopback, or a
microphone. You can change your mind later; what matters now is that the
meeting exists to prepare for.

Which engagement and which meeting you are working on is chosen in the toolbar
at the top of the window, and it follows you between screens.

## Add what you already have

Scoping decks, throughput studies, the last proposal. Drop the files straight
onto the screen, or attach them by their SharePoint, OneDrive or Teams link —
the only kinds of link Elicta accepts, so that what it reads is the copy your
client can also see rather than one that has quietly drifted.

Either way Elicta reads what is inside: Word, PowerPoint, Excel and PDF, not
just the filename. A link is refused rather than half-attached if it cannot be
opened, because a document nobody can read contributes nothing and should not
sit in the list looking as though it does.

Each document gets tagged as one of three things, and the tag changes how
Elicta treats it:

- **Ground truth** — established fact. If a client contradicts it, that is worth
  interrupting for.
- **Hypothesis** — our assumption, not theirs. It generates questions to verify
  rather than contradictions to flag.
- **Superseded** — kept for background, never used to challenge anyone.

You also add the words the client uses that a transcriber would not know:
product names, internal systems, their own jargon. This is the single most
effective thing you can do for accuracy. A misheard product name does not just
look sloppy — it reads to Elicta as something brand new, and it will interrupt
you to ask about a system that does not exist.

## Review the questions before anyone asks them

Elicta reads everything and drafts the questions worth asking, grouped by the
section of the requirements template each one serves. You read them, move the
ones that matter up the list, and prune the ones that miss. A pruned question
stays pruned: it is recorded as your judgement rather than deleted, so it does
not come back the next time the bank is drafted.

A real bank runs to seventy-odd questions across the eight sections, so the
sections open one at a time and each says how many are inside it before you
open it. There is also a box that filters the whole bank by what a question
says, which is how you find the four that mention a particular system without
reading the other seventy. Reordering is off while that filter is on: moving a
question up means moving it past the one above it, and under a filter the
question above on screen is not the one above in the bank.

![The preparation screen: documents, client vocabulary, and the question bank grouped by section](screenshots/prep-question-tree.png)

This review is worth doing even if you never open Elicta during the meeting.
A good question list makes you better prepared on its own — which is why it
comes first, and why you are meant to edit it rather than trust it.

## Where this stands

| | |
|---|---|
| ✅ Ready | Creating engagements and the meetings inside them — the first one and every one after it; adding documents by dropping the files in or by link, and tagging them; reading what is inside them; the client vocabulary list; and reviewing, reordering and pruning the question bank — all of it from the screen, and all of it within one sitting |
| ✅ Ready | **All of it is kept.** The engagement, its meetings, the documents you attach and their contents, the words you add, and the question bank are written to a single file on your machine as you go. Nothing needs installing for that, and a firm that wants everything on its own database server can point Elicta at one instead |
| ✅ Ready | **Taking things back out.** A document, a word or the whole engagement can be removed from the screen. Nothing is erased: the record is kept and can be brought back, which is why removing a client here is a tidying-up action and not a way to honour a request to be forgotten |
| ⏳ Not yet | Erasing a client's data outright, and the engagement list showing more than the first twenty |
| ⚙️ Setup | Two one-off steps, both in Settings and both covered in journey 10. Drafting the questions needs an AI provider. Reading a document from SharePoint or OneDrive needs your Microsoft 365 tenant registered — a dropped file needs neither, which is the way in that always works |
| ✅ Ready | **Collecting the drafted questions.** Drafting is submitted as a job that finishes minutes later; the service now goes back for the result every thirty seconds, puts the questions in the bank, and stops asking once a job has ended, failed or expired. A compile that stops for any other reason now says so in the log instead of leaving an empty bank and no explanation |
| ✅ Ready | **The screen says why the bank is empty.** Compiling answers "accepted" whatever happens next, and the bank answers an empty list whatever the reason, so between them they said nothing at all about four consecutive failures — the screen read "Not compiled yet" every time, after four compiles had run. It now names the step that stopped and what to do: nothing set up, a credential that may not use the model, a token that cannot submit the drafting job, a provider being throttled, or a network that could not be reached. Those have four different fixes and one of them is not "wait" |
| ✅ Ready | **A refusal that waiting cannot fix is no longer filed as a throttle.** A model outside a credential's plan is refused with the same status as a rate limit, and Elicta read it as one — its own message said "check the model in Settings" while the category it was filed under said "try again shortly". Anything reading the category, which is what a screen must do, repeated the advice the message had just ruled out |
| ✅ Ready | **Compiling no longer holds the request open.** `Compile` answered "accepted" only once the whole chain had run — measured against a real provider, 45 seconds for a status whose entire meaning is that the work is happening elsewhere. Any client giving up at thirty seconds saw a failure for a compile that was running perfectly well, and pressing the button again started a second one. It now answers in milliseconds, the screen says while it is working, and the button will not start another on top of it |
| ✅ Ready | **A credential that cannot submit a batch job can still draft a bank.** The drafting pass is handed to a cheaper, slower way of asking that some accounts are not permitted to use, and that was the only way it was ever asked — so those accounts could never produce a bank at all, however many times Compile was pressed. Where the cheap route is refused for want of permission, the same pass is now asked the ordinary way instead. Only a permission refusal falls back: a provider that is simply unreachable will answer the second call exactly as it answered the first |
| ✅ Ready | **A bank is drafted end to end, on this credential.** The whole chain runs against a live model — reading the documents, sorting what is in them, and drafting the questions — and the questions reach the screen. Two things had to change for that. The acceptance check demanded at least 150 questions, which is what a good pass over a real document set produces and not what an acceptance check should insist on: a perfectly good pass over three short documents came back with twelve and was thrown away whole. That check now catches a pass that did not really answer, and leaves judging the volume to whoever reads the bank |
| ✅ Ready | **The bank is filed under sections somebody chose, not sections a compile invented.** Nothing ever told the drafting pass which sections exist — it was asked to use "the sections the documents imply", so it invented one called *Operations* and put 65 of 97 questions in it. That is a bin rather than a section: it cannot be reviewed section by section, two engagements filed under different sections cannot be compared, and coverage is tracked against sections the meter has to have heard of. The sections now travel with each request as a closed list, and a live compile spread 73 questions across all eight, the largest section holding eleven |
| ⏳ Not yet | **Sections that come from the engagement's own template.** An engagement names its target requirements template as free text, and nothing turns that name into a section list — so the list above is a stated default rather than the template the client asked for. The write-up still classifies against no sections at all, which is the same gap one step further on |
| ✅ Ready | **The drafting pass is asked for the right thing.** It was being sent the *debrief's* instructions — produce open questions, a decision log, a project brief and a follow-up email, citing the transcript. There is no transcript before a meeting, and what is wanted is a bank of questions tagged with the template section each one serves. The model did as it was told: a live compile filed its candidates under "open questions" and "decision log", and half of them were statements rather than questions. The two passes now have their own instructions |
| ⏳ Not yet | **Remembering a failed compile across a restart.** The explanation above lives only as long as the service does. Restart it and the screen goes back to offering a compile, which is a fair trade — a failure kept from before a restart might describe a problem you have already fixed — but it does mean pressing Compile again is how you get the current answer |
| ⏳ Not yet | A scanned PDF. The text of a page that is really a photograph is not recovered, so such a document contributes nothing rather than contributing nonsense |
