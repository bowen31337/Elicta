# The Elicta Handbook

Read it: start at [`index.md`](index.md).

Everything else in this file is about *maintaining* the handbook. The chapter
[How This Handbook Stays True](chapters/30-how-this-handbook-stays-true.md) covers the same
ground for readers; this is the short operational version.

## Layout

```
handbook/
├── README.md              this file — how the handbook is maintained
├── STYLE.md               the writing contract
├── book.toml              the chapter manifest; the only list of chapters
├── index.md               GENERATED — table of contents
├── handbook.pdf           GENERATED — the whole handbook, bound
├── drift.lock.json        GENERATED — what a human last confirmed
├── chapters/
│   ├── 01–07              prose, written by people
│   ├── 20–25              GENERATED reference, derived from the code
│   └── 30–31              prose, about the handbook and the traps
└── tools/                 the generator, stdlib only, tests beside the code
```

## The four commands

```bash
python3 handbook/tools/gen.py build     # chapters, index, footers and the PDF
python3 handbook/tools/gen.py check     # errors block CI; warnings ask a human
python3 handbook/tools/gen.py status    # inventory and drift state
python3 handbook/tools/gen.py pdf       # rebuild the bound PDF on its own
python3 handbook/tools/gen.py accept --chapter <id>
```

To read the PDF in an editor that renders images but not PDFs — Zed among them —
rasterise it first (needs poppler; output is git-ignored):

```bash
bash handbook/tools/preview.sh          # handbook/preview/page-01.png, ...
```

`handbook.pdf` is written by `build` and is a committed artifact, like the
generated API client. It is rewritten only when the chapters or the rendering
code change — the file carries a digest of its own sources, and `check` reports
`stale-pdf` when they no longer match.

Run the generator's own tests with the standard library runner — `pytest` does not collect
them, because its `testpaths` is `apps/service/src`:

```bash
cd handbook/tools && python3 -m unittest
```

## After shipping a feature

Use the `/handbook-sync` slash command, or by hand:

1. `build`, and read what it rewrote. New commands, routes or configuration keys appearing in
   the reference chapters are the signal that prose chapters need attention too.
2. `check`, and fix every error. All of them are machine-fixable.
3. Work through the drift warnings: read the chapter, read the diff of what it watches,
   decide honestly, fix if needed, then `accept --chapter <id>`.
4. `check` again, then `build` again — the second build must produce no diff. CI checks this,
   because a generator that is not reproducible cannot be a gate.
5. Commit the chapters together with `drift.lock.json`.

## Two rules the checks enforce

The handbook is read outside the team as one bound document. So a prose chapter
may contain **no links** and **no requirement identifiers**; both are errors, not
style notes. Say the thing where the reader is standing. `STYLE.md` has the
detail, and one chapter carries a documented exemption.

Diagrams go in ` ```diagram ` blocks and are drawn as pictures. Mermaid is still
rendered, as a source panel, but should not be used in new chapters.

## Never

- **Never edit a file carrying `<!-- HANDBOOK-GENERATED -->`.** The next build reverts it.
- **Never hand-edit `handbook.pdf`.** Change a chapter, or change `typeset.py`.
- **Never `accept` a chapter you did not re-read.** The lock is a record of human
  confirmation; baselining to clear output empties it of meaning.
- **Never delete an entry from `BANNED_CLAIMS` to make `check` pass.** If the claim became
  true, verify it in the source, then remove the entry and say so in the commit message.

## Enforcement

Three overlapping places, because any one can be bypassed:

| Where | What |
|---|---|
| `.github/workflows/test.yml` | The `handbook` job: unit tests, `check`, then `build` and fail on any diff |
| `.claude/settings.json` | A `Stop` hook running `tools/hook_check.py` — a session cannot end stale |
| `tools/install-git-hooks.sh` | An opt-in pre-commit hook running `check` |
