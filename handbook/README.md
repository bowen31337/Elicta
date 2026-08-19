# The Elicta Handbook

Read it: `handbook/handbook.pdf`, or start at [`index.md`](index.md).

**It is a guide for the people who use Elicta, not for the people who build it.**
That is the single most important thing to know before editing it. It carries no
description of how the software works internally — no components, no network
interfaces, no build commands — and the checks enforce that. Technical
documentation lives in `CLAUDE.md` and `docs/`.

## Layout

```
handbook/
├── README.md              this file — how the handbook is maintained
├── STYLE.md               the writing contract
├── book.toml              the chapter manifest; the only list of chapters
├── index.md               GENERATED — table of contents
├── handbook.pdf           GENERATED — the whole guide, bound, with screenshots
├── drift.lock.json        GENERATED — what a human last confirmed
├── chapters/              one file per chapter
└── tools/                 the generator, stdlib only, tests beside the code
```

## The four commands

```bash
python3 handbook/tools/gen.py build     # chapters, index and the PDF
python3 handbook/tools/gen.py check     # errors block CI; warnings ask a human
python3 handbook/tools/gen.py status    # inventory and drift state
python3 handbook/tools/gen.py pdf       # rebuild the bound PDF on its own
python3 handbook/tools/gen.py accept --chapter <id>
```

Run the generator's own tests with the standard library runner — `pytest` does
not collect them, because its `testpaths` is `apps/service/src`:

```bash
cd handbook/tools && python3 -m unittest
```

To read the PDF in an editor that renders images but not PDFs, rasterise it
first (needs poppler; output is git-ignored):

```bash
bash handbook/tools/preview.sh
```

## Screenshots

Chapters show real screens, taken from `docs/journeys/screenshots/` and embedded
in the PDF:

```markdown
![What the caption says](../../docs/journeys/screenshots/panel-asked-it.png)
```

A line that is nothing but a picture becomes a picture. Three things happen
automatically and are worth knowing:

- **The blank tail is cropped.** A screenshot of a mostly-empty panel would
  otherwise waste half a page. The crop is done with a clipping path, so the
  file itself is untouched and the same picture can appear cropped in one place
  and whole in another.
- **A picture taller than it is wide is held back from the full text width**, so
  a narrow panel does not read as a full-screen application.
- **A picture that cannot be read leaves a visible note naming the file**, rather
  than a silent gap. A renamed screenshot is obvious in the document.

## Two rules the checks enforce

The guide is read as one bound document by people outside the team, so a chapter
may contain **no links** and **no requirement identifiers**. Both are errors, not
style notes. `STYLE.md` has the detail.

## After shipping a feature

Use the `/handbook-sync` slash command, or by hand:

1. `build`, and read what it rewrote.
2. `check`, and fix every error. All of them are machine-fixable.
3. Work through the drift warnings: read the chapter, look at what changed in the
   screen it describes, decide honestly, fix if needed, then
   `accept --chapter <id>`.
4. **Look at the screenshots.** Drift on a screen usually means the picture is
   out of date, and no check can see that. `docs/journeys/screenshots/` is
   captured from the running app.
5. `check` again, then `build` again — the second build must produce no diff.
6. Commit the chapters together with `drift.lock.json` and `handbook.pdf`.

## Never

- **Never edit a file carrying `<!-- HANDBOOK-GENERATED -->`.** The next build
  reverts it.
- **Never hand-edit `handbook.pdf`.** Change a chapter, or change `typeset.py`.
- **Never `accept` a chapter you did not re-read.** The lock is a record of human
  confirmation; baselining to clear output empties it of meaning.
- **Never delete an entry from `BANNED_CLAIMS` to make `check` pass.** If the
  claim became true, verify it in the source, then remove the entry and say so in
  the commit message.

## How it stays true

| Half | How |
|---|---|
| Generated chapters | Rebuilt from their sources and compared byte for byte. `stale-generated` is an error. |
| Prose chapters | Each declares in `book.toml` the paths it describes. When those move, `check` reports `drifted` — a warning, because only a person can say whether the words and the pictures are still right. |
| The PDF | Carries a digest of the chapters and the rendering code in its own metadata. `stale-pdf` is an error. |

Enforced in three overlapping places, because any one can be bypassed:

| Where | What |
|---|---|
| `.github/workflows/test.yml` | The `handbook` job: unit tests, `check`, then `build` and fail on any diff |
| `.claude/settings.json` | A `Stop` hook running `tools/hook_check.py` — a session cannot end stale |
| `tools/install-git-hooks.sh` | An opt-in pre-commit hook running `check` |

## Generators that are not used

`tools/generators.py` still holds generators that describe the software's
internals. They are working and tested, and they are **not** mounted in
`book.toml`, because this is a guide for users. Each is named in `UNMOUNTED`
with the reason, and a test asserts that every generator is either mounted or
listed there — so "built and quietly wired to nothing" cannot happen by accident.

If a companion document for engineers is ever wanted, those generators are what
it would be built from.
