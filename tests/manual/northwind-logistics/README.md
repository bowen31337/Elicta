# Northwind Logistics — documents for testing preparation by hand

Five reference documents for one fictional client, for driving journey 1
(*Prepare for the engagement*) through the running app yourself.

They are not filler. Each one carries something a specific part of Elicta is
meant to react to, and they disagree with each other on purpose — the
disagreements are the point, because a document set that all says the same
thing tests nothing beyond whether upload works.

## The client

**Northwind Logistics** is rebuilding depot scheduling across three sites:
Felixstowe, Rotterdam and Shenzhen. The Shenzhen site is what makes Elicta
expect Mandarin in the room without anyone choosing a language, so it is worth
putting in the commercial context when you create the engagement:

| Field | Suggested value |
|---|---|
| Client organisation | `Northwind Logistics` |
| Sector | `Freight and logistics` |
| Commercial context | `Depot scheduling rebuild across Felixstowe, Rotterdam and the Shenzhen depot team` |

## The documents, and what each is for

| File | Tag it as | Why |
|---|---|---|
| `01-scoping-deck.pptx` | **Ground truth** | The client's own pack. If they contradict it in the room, that is worth interrupting for |
| `02-throughput-study.xlsx` | **Ground truth** | Their measured volumes, with the caveats attached |
| `03-integration-assumptions.docx` | **Hypothesis** | Ours, not theirs. Every line is something to verify |
| `04-proposal-2024-superseded.pdf` | **Superseded** | Last year's proposal, kept for background, never used to challenge anyone |
| `05-shenzhen-briefing-note.docx` | **Ground truth** | Half English, half Mandarin — the one that exercises the language handling |

Drop them onto the Preparation screen, or upload them one at a time. The tag is
chosen **as you attach**, not afterwards — the upload refuses a document that
arrives without one.

All five have been put through the real upload endpoint and come back out of
the state database with their text intact: 1,226 characters from the deck, 518
from the study, 1,133 from the assumptions, 626 from the PDF and 432 from the
briefing note. A document that lands in the list and in no index is invisible
to everything downstream, so that is worth checking rather than assuming.

The Word and Excel files are complete packages and open normally. **The
PowerPoint deck does not** — it carries slide parts and nothing else, because a
slide is meaningless to PowerPoint without a layout, which needs a master,
which needs a theme. Elicta reads only the slide parts, so the deck is a reader
fixture; its content is written out in `build.py` if you want to read it.

## Client vocabulary worth adding

These are the words a transcriber would not know, and a misheard product name
reads to Elicta as something brand new:

| Term | Type |
|---|---|
| `Zephyr WMS` | Product name |
| `Northwind` | Client name |
| `Felixstowe` | Place |
| `consignment` | Domain term |
| `TMS handoff` | Domain term |
| `slot booking` | Domain term |

## What to look for

**The order-of-magnitude conflict.** The throughput study says Felixstowe
handles **3,500,000** consignments a year. The 2024 proposal says **350,000**,
and the assumptions document repeats the smaller figure and says out loud that
it came from the proposal. One of these is wrong by a factor of ten, and it is
exactly the kind of number a write-up would carry all the way through without
anyone noticing. The superseded tag is what should stop the old figure being
used to challenge anybody.

**The vague requirements.** Slide 3 of the deck is four sentences with nothing
measurable in any of them — *fast*, *visibility*, *scale*, *modern and
flexible*. That slide exists to give the question bank something to bite on.

**The things nobody has measured.** The Shenzhen row of the throughput study
says "not yet measured" three times, and the deck says the same in prose. A
good question list should want those numbers.

**The contradiction between what we assume and what they said.** The
assumptions document says Zephyr WMS exposes a REST API we can call in near
real time. The client's own deck says the handoff is a nightly CSV and it is
often wrong. That is a hypothesis meeting a ground truth, and the two should be
treated differently — a hypothesis generates a question to verify, not an
accusation.

**The language.** The briefing note is deliberately bilingual, and mentions
`三百五十万` — the same 3,500,000 in Chinese numerals. With Shenzhen in the
commercial context, the live panel should show that it is *listening for* both
English and Mandarin before anyone speaks.

## What will not work yet, and is not your fault

Worth knowing before you read anything as a bug:

- **Drafting the question bank needs a provider that can submit a batch job.**
  The Analyst pass is submitted as a batch and collected minutes later. A
  credential without that permission is refused outright, and the bank stays
  empty.
- **Nothing is transcribed.** There is no speech-vendor client on either path,
  so no meeting produces suggestions, and the write-up stops at its first step.
  The preparation half of journey 1 is fully usable regardless.
- **A scanned PDF yields nothing.** `04-proposal-2024-superseded.pdf` is real
  text and reads fine. A PDF that is really a photograph of a page contributes
  nothing rather than contributing noise, which is deliberate.

## Rebuilding them

```bash
python3 tests/manual/northwind-logistics/build.py
```

Edit the content at the bottom of `build.py` and re-run. The generated files are
committed, so you do not need to.

The builder uses `zipfile` and `zlib` and nothing else, because that is all
Elicta's own reader uses — a document produced by a real Office library that
Elicta could not read would be a fixture that tests the fixture rather than the
product.

## One thing seen once and not explained

The first upload of the deck returned **500** on a running service. It has not
happened again across four subsequent attempts — in memory, against SQLite, and
twice more against the same live service — and the traceback was lost because
that service's output went to a pipe with no reader. It is recorded here
because a transient 500 nobody wrote down is a transient 500 that gets
rediscovered. If you meet one, capture the service log before retrying.
