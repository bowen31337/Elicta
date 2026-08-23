# Elicta Quick Start

Your first hour with Elicta, in the order you will meet it.

Elicta helps you ask the question you would otherwise have missed — while the
client is still in the room — and then writes up what was agreed, quoting the
words that were actually said.

The one thing to understand before you start: **almost everything that makes
Elicta useful happens before anyone sits down.** The thinking is done days in
advance so that during the meeting it only has to pick the right question from
work already finished. If you do nothing else from this guide, do steps 2 to 5.

Read this in one sitting; the whole first pass takes about an hour, most of
which is waiting for the question bank to draft.

The rest of this book walks the same path slowly, one screen at a time. This
chapter is the short way through it.

---

## Before you begin

You need one thing that somebody has to give you: **a credential for an AI
provider**. Elicta uses outside services for two jobs — turning speech into
text, and doing the writing-up — and the question drafting is the one you will
hit in your first hour.

Two things you do *not* need:

- **A database.** Everything an engagement remembers is written to a single
  file on your machine as you work. Nothing to install.
- **A Microsoft 365 registration** — unless you want to attach documents by
  SharePoint or OneDrive *link*. Dropping the files in needs nothing set up at
  all, and is the way in that always works.

---

## Step 1 — Point Elicta at the services it uses

*Settings. Once, per machine. Five minutes.*

On first run the Settings screen says plainly that nothing is configured,
rather than looking ready and failing later. A tab whose service still needs
something carries a small mark, so what is left to do can be read from the row
of tabs before you open any of them.

![Before anything is configured](../../docs/journeys/screenshots/settings-first-run.png)

The screen is a row of tabs with one thing behind each. Most are an outside
service, and that service's credential sits behind its own tab under the name of
the company that issued it — there is no list of keys to work out which goes
where. The rest are choices about your own installation, and you can leave those
as they are for now.

Fill in the first tab, which is the service that does the writing-up. You can point Elicta at the company that makes
the service directly, at Amazon's, Google's or Microsoft's hosted versions, or
at your organisation's own gateway. Choose Amazon or Google and no key is asked
for at all — Elicta uses the permissions your cloud account already grants it,
and the credential fields do not appear rather than sitting there greyed out.

![Credentials configured, with the one in use marked](../../docs/journeys/screenshots/settings-configured.png)

Then press **Test**. It really tests — it checks the credential against the
service rather than reporting "configured" as though that meant "working".

Four behaviours here will look odd until you know why:

| What you see | Why |
|---|---|
| The key field is always empty | Elicta never sends a stored key back to the screen. It shows the last four characters instead, which is enough to tell one key from another. |
| Leaving it blank keeps the old one | So saving an unrelated setting cannot wipe your key by accident. |
| **Clear** is a separate button | Removing a credential is its own deliberate action, because it cannot be undone. |
| Key *or* token, never both boxes | You say which kind you have and only that one is asked for. |

**Transcription services can wait.** They are set up separately, and in this
build nothing is connected to them yet — see *What to expect* below. Skip them
on your first pass.

---

## Step 2 — Add your client

*Engagements. Two minutes.*

Elicta opens on your clients. Each one is an **engagement**, and adding one asks
three things: who they are, the sector, and the commercial shape of the work.

![Your clients, and the form for adding one](../../docs/journeys/screenshots/engagements-list.png)

That is not filing. It is what lets Elicta work out which languages to expect in
the room, so nobody has to be asked to choose one before a meeting starts.

Opening a client makes it the one every other screen is about.

> **The single most common confusion.** A screen that looks empty is far more
> often pointed at a different client than genuinely empty. The switcher at the
> top of the window, beside the screen's name, follows you everywhere — that is
> the first place to check. Your choice is remembered between sessions.

---

## Step 3 — Add its first meeting

*One minute.*

An engagement is a client. A **meeting** is one conversation with them — and
everything after this point (recording, the live panel, the write-up) is about a
meeting, so an engagement needs at least one before any of it applies.

Adding one asks a single question: how the audio will reach Elicta. A line-in
from the meeting machine, a silent join that takes the call audio, or a
microphone. You can change it later.

---

## Step 4 — Give it what you already have

*Preparation screen. Ten to twenty minutes, and the highest-value time you will
spend.*

**Documents.** Scoping decks, throughput studies, the last proposal. Drop the
files straight onto the screen, or pick them with the button beside the drop
area. Elicta reads what is *inside* them — Word, PowerPoint, Excel and PDF
alike, not just the filename.

Tag each one, because the tag changes how Elicta treats it:

| Tag | What it means |
|---|---|
| **Ground truth** | Established fact. If a client contradicts it, that is worth interrupting a meeting for. |
| **Hypothesis** | Our assumption, not theirs. Produces questions to verify, not contradictions to flag. |
| **Superseded** | Kept for background, never used to challenge anyone. |

You can also attach a document by its SharePoint, OneDrive or Teams link — but
that is the one thing here that must be set up first, and until it is, pasting a
link is refused with a message saying so. That refusal is deliberate: a link
recorded but never read would sit in the list looking like preparation that had
happened.

**The client's own words.** Product names, internal systems, their jargon — the
words a transcription service has no way of knowing.

> This is the most effective single thing you can do for accuracy, and it is
> worth more than any other preparation on this screen. A misheard product name
> does not just look sloppy: it reads to Elicta as something brand new, and it
> will interrupt you to ask about a system that does not exist. A typo in this
> list is worth correcting the moment you notice it — a wrong word handed to the
> transcription service is worse than no word at all, because it makes the
> transcript confidently wrong rather than merely uncertain.

Nothing you remove here is erased. A document's **Remove**, a word's small **×**,
and removing the whole engagement all just stop it appearing; the record is kept.
So tidy freely — but know that removing a client is *not* how you would honour a
request to erase their data. Elicta does not do that yet.

---

## Step 5 — Draft the questions, then read them

*Press Compile, then go and make coffee.*

Elicta reads everything you gave it and drafts the questions worth asking,
grouped by the section of your requirements template each one serves.

![The preparation screen: documents, vocabulary, and the question bank grouped by section](../../docs/journeys/screenshots/prep-question-tree.png)

Drafting is slow work, so it is handed off as a job that finishes some minutes
later; Elicta goes back for the result on its own and fills the bank when it
arrives. **Compile before you make coffee, not while the client is waiting.**
While it is working the screen says so, and will not let you start a second one
on top of it.

Then do the part that matters: **read the questions, move the ones that matter
up, and prune the ones that miss.** Pruning is not deletion — a pruned question
is kept as a record of your judgement and stays pruned in every later meeting,
so redrafting the bank never brings it back for you to reject twice.

This review is worth doing even if you never open Elicta during the meeting. A
good question list makes you better prepared on its own, which is why it comes
first and why you are meant to edit it rather than trust it.

### If the bank comes back empty

The screen tells you which of these it was — it names the step that stopped and
what to do about it. The four causes have four different fixes, and only one of
them is waiting:

1. **Nothing set up** — drafting needs the AI provider from step 1.
2. **Nothing was read** — if every document you added was a *link* and your
   Microsoft 365 tenant is not registered, none of them were read. You would
   have seen each link refused at the time. Drop the files in instead.
3. **It is still working** — normal. Give it minutes, not seconds.
4. **A credential problem** — a key not permitted to use the model you chose, a
   provider throttling you, or a network it could not cross.

One kind of document contributes nothing either way: a **scanned PDF**, where
the page is really a photograph of a page. Elicta will not guess at words in a
picture, so it adds nothing rather than nonsense. If a scan is the only copy you
have, put that document's important words in the vocabulary list instead.

---

## Step 6 — Run the meeting

**Consent first, and in this build it is yours to handle.** As it ships today,
Elicta does not stop to ask for consent before a meeting, and writes no consent
record. The screen says so in as many words, and is careful to report that
nothing has been recorded here rather than showing you a reassuring tick.

![Consent is not being asked for, and nothing is on record](../../docs/journeys/screenshots/consent-not-asked.png)

So having the consent conversation — and being able to show later that you had
it — rests with you, not with the software. The gate that would hold recording
shut is built and works, but nothing can switch an engagement over to it yet.

**What you can tell the client about the audio,** truthfully, before a second of
it exists: Elicta writes no copy of it anywhere, it is held only for as long as
it takes to turn it into text, it is destroyed the moment that finishes — and the
deletion is itself recorded — and the transcription service is told with every
request not to keep it.

**Starting.** Pick the input before you start, rather than discovering afterwards
that it took the wrong one, and press *Check microphone* first: it opens the input
and shows the level moving without recording anything, which is also what makes a
browser tell Elicta the real names of your microphones. Starting the recording is
what registers the meeting, and the input is opened before that happens, so a
microphone that will not open registers nothing. Elicta will argue for a better microphone: a wired
input or a silent join is markedly more accurate than a mic in the middle of the
table, because people talking over each other causes more transcription errors
than the choice of service does. A room mic earns a warning that stays on screen.

![Recording, with pause one tap away](../../docs/journeys/screenshots/capture-recording.png)

**Pause is the control to know.** You reach for it when a client says *"can we
take this bit off the record."* It is the largest thing on the screen, never
moves, takes effect immediately, and does not ask whether you are sure. Stopping
sits beside it, deliberately smaller — it ends the recording and hands the
microphone back, and is not what you want under your thumb when you meant to
pause. Audio captured while paused is discarded, and resuming is instant.

![Paused, and saying so unmistakably](../../docs/journeys/screenshots/capture-paused.png)

The state is said three ways at once — the word, the sentence under it, and the
colour — and never by colour alone, because believing you are paused while still
recording is the worst thing this product could do to you.

**The panel,** when a suggestion arrives, gives you three things in the order you
need them: the short version readable without breaking eye contact, the full
wording if you want to ask it verbatim, and quietly underneath, *why it fired* —
which is how you tell in half a second whether Elicta understood the room.

![A suggested question, and why it fired](../../docs/journeys/screenshots/panel-nudge-surfaced.png)

Every response is one tap: **Asked it** (the section fills in immediately),
**Park it** (kept for the write-up), **Go deeper** (follow the thread), or
**What am I missing?** (it names the biggest uncovered topic).

---

## Step 7 — Afterwards

Open the debrief screen and **ask about the meeting in your own words** — *what
did they actually say about the March deadline*, *draft me the paragraph about
integrations*. Answers quote and attribute rather than summarise, and say plainly
when something was worked out rather than said.

![Asking a question about the meeting in your own words](../../docs/journeys/screenshots/debrief-conversation.png)

The intended output is four documents: the open questions ranked by how much they
matter, a log of decisions, a draft project brief, and a follow-up email for you
to read and send — never sent for you. Every claim carries its source, and is
labelled **Stated** (the client said it; check the wording) or **Inferred**
(Elicta concluded it; judge whether you agree). A claim without a source cannot
be saved at all.

If a step of the write-up fails, the sequence stops there and says which step and
why, rather than passing invented material to the next one. A partial result with
an explanation is recoverable; a complete-looking document with a fabricated
section is not.

**Into the next meeting,** the open questions lead the screen, ahead of completed
work — what you settled is behind you, and what you did not is what you are
walking back in to deal with. A question that has come through three meetings
unanswered is flagged, because there are only two explanations and both matter:
it is genuinely hard, or it is being deflected.

---

## What to expect on your first run — honestly

This build is not finished, and it is better to know where before your first
client meeting than during it.

What is finished changes with every build, so this chapter deliberately does
not list it. The last chapter of this book does, and it is rewritten from the
product's own notes each time the book is built — which is why it is the one
to read before you promise anything to anyone. A list copied into this chapter
would be out of date within a fortnight and would look just as confident.

The honest shape of your first real meeting, in a sentence: **Elicta is a very
good prepared-question list, a recorder, and an after-the-fact way to
interrogate what was said** — and, once a speech provider is configured, a
panel that puts a question in front of you while the client is still in the
room. That last part is the thing it is ultimately for, and it now works for
vague wording. What it does not yet do is in the last chapter.

---

## If something looks wrong

| Symptom | First thing to check |
|---|---|
| A screen is empty | The client switcher at the top of the window. It is far more often pointed elsewhere than genuinely empty. |
| The question bank is empty | The screen names which of the four causes it was. Note that a failed compile's explanation does not survive restarting the service — press Compile again to get the current answer. |
| Pasting a document link is refused | Microsoft 365 registration is not set up. Drop the file in instead; that path needs nothing. |
| **Start recording** is greyed out | The screen says which: the page is not secure, the browser offers no microphone access, or the machine has no microphone attached. |
| No microphone in a browser | Browsers only hand it over on a secure page — on a plain address the capability is *absent*, not blocked, so there is no prompt to accept. That one is yours to fix and takes a moment. |
| A permission prompt during a client meeting | It should have been pushed out through device management, which grants microphone and screen-recording access centrally. Agree the endpoint-security exception *before* the pilot, not during it — it is the single most common cause of a bad first impression. |

---

## What Elicta deliberately will not do

Worth knowing on day one, because each is a choice rather than a gap:

- **It never speaks to the client.** No voice, no messages, nothing on your
  behalf. Ignore it for ninety minutes and nothing happens — that is a supported
  way to use it.
- **You cannot talk to it during a meeting.** Anything inviting you to type has
  taken your attention off the client, which is the exact problem it exists to
  relieve. Asking it things in your own words is an afterwards activity.
- **It stays quiet when unsure.** One suggestion that embarrasses you in front of
  a client does more damage than ten good ones repair, so it will sometimes miss
  what a sharp analyst would have caught. That trade was made knowingly.
- **It does not replace judgement.** It notices, suggests, and writes down what
  it heard. What matters, what to push on, and when the room has had enough stays
  with you.

---

## The five-minute version

1. Settings → first tab → fill it in → **Test**.
2. Add the client. Add a meeting to it.
3. Drop your documents on the Preparation screen. Tag them.
4. Type the client's product names and jargon into the vocabulary list.
5. **Compile.** Go and make coffee.
6. Read the drafted questions. Reorder. Prune.
7. Walk into the meeting better prepared than you were — which is most of the
   value, and available today.

---

## Where to read more

Everything here is covered again slowly in the chapters that follow, with every
screen shown. The one to read next is the chapter on preparing for an
engagement, because that is where the hour you spend pays for itself. The one to
read before you promise anything to anyone is the last chapter, on what works
today.

<!-- HANDBOOK-NAV -->

---

[Contents](../index.md) · [What Elicta Does](01-what-elicta-does.md) →
