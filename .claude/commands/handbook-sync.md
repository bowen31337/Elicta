# Sync the Handbook

Bring `handbook/` back in line with the code after a feature landed or changed.
Regenerates the reference chapters, then works through whatever the drift
checker says still needs a human.

Use this after shipping anything that changes a crate, an API route, a service
module, a desktop feature, a configuration variable, a slash command, or the
behaviour a chapter describes.

The handbook is English-only.

## Before you start

Read `handbook/README.md` (the workflow) and `handbook/STYLE.md` (the writing
contract). The generator is standard library only — there is nothing to install
and no project to activate.

## Step 1 — Regenerate and see where you stand

```bash
python3 handbook/tools/gen.py build
python3 handbook/tools/gen.py status
```

`build` refreshes the generated reference chapters, `index.md`, the navigation
footer of every chapter, and the bound `handbook/handbook.pdf`. It never touches
hand-written prose above the `<!-- HANDBOOK-NAV -->` marker, and it never writes
`drift.lock.json`.

The PDF is rewritten only when its source digest moves — the chapters, the
manifest, or `pdf.py` / `mdread.py` / `typeset.py`. `gen.py pdf` forces it.

Report to the user what `build` changed. New crates, routes or configuration
keys appearing in the reference chapters are the signal that prose chapters
likely need work too.

## Step 2 — Fix every error

```bash
python3 handbook/tools/gen.py check
```

Errors block CI, and each one is machine-fixable. Work through them:

| Error kind | What to do |
|---|---|
| `stale-generated` | Re-run `build`. If it persists, the generator is non-deterministic — fix `handbook/tools/render.py`. |
| `missing-page` | Re-run `build` to scaffold it, then write the chapter. |
| `orphan-page` | Markdown under `handbook/` that no chapter claims. Add a `[[chapter]]` entry to `handbook/book.toml`, or delete the file. |
| `dead-link` | Fix the link target. Chapter filenames are in `handbook/book.toml`. |
| `no-h1` / `multiple-h1` / `title-mismatch` | A chapter has exactly one H1 and it matches `book.toml`. |
| `mermaid-*` | Fix the diagram: known diagram type, balanced brackets, non-empty block. |
| `duplicate-nav` | Delete everything from the first `<!-- HANDBOOK-NAV -->` marker, then re-run `build`. |
| `generated-marker-in-prose` | A prose chapter carries the generated marker. Remove it, or change its `kind` in `book.toml`. |
| `missing-pdf` / `stale-pdf` | Re-run `build` (or `gen.py pdf`). Commit `handbook/handbook.pdf` with the chapters. |
| `cross-reference` | A chapter links somewhere. The handbook is read as one bound document by people outside the team — say the thing in place instead of pointing. |
| `spec-reference` | A chapter cites a requirement identifier, architecture section or decision record. State it in words; the reader has none of those documents. |
| `false-claim` | **Read carefully** — see below. |

### On `false-claim` errors

`handbook/tools/lint.py` holds `BANNED_CLAIMS`: statements that appear in this
repo's older documentation and are not true of the code — that `./run.sh` is
usable, that formatting is gated in CI, that routes can be counted off
`app.routes`, that a hyphenated service module can be imported literally, and
so on. Each entry carries the reason it is false.

Two legitimate responses, and one wrong one:

- **The chapter was prescribing it** → remove it and describe what actually
  works. This is usually the right answer.
- **The chapter is warning readers about it** (`31-troubleshooting.md` does this
  deliberately) → add `<!-- lint-allow: <tag> -->` to that page.
- **Never** delete the entry from `BANNED_CLAIMS` to make the check pass. If a
  claim became true because someone implemented the thing, then remove the
  entry — but verify it in the source first, and say so in the commit message.

## Step 3 — Work through the warnings

Warnings name chapters whose watched sources moved (`drifted`), chapters never
confirmed at all (`unbaselined`), and chapters still scaffolds (`stub-page`).
For each drifted chapter:

1. Read the chapter.
2. Read the diff of the sources it watches — `book.toml` lists them per chapter.
3. Decide honestly: is the chapter still accurate?
   - **Still accurate** → nothing to write; it just needs re-baselining.
   - **Now wrong or incomplete** → update it.
4. Baseline it:

```bash
python3 handbook/tools/gen.py accept --chapter <CHAPTER_ID>
```

> [!IMPORTANT]
> Only run `accept` for chapters you actually re-read. Baselining everything to
> clear the output defeats the entire mechanism — the next real change will not
> be noticed by anybody. `accept --all` exists to seed a fresh lock, not to
> silence warnings.

## Step 4 — Verify

From the repository root:

```bash
(cd handbook/tools && python3 -m unittest)   # the generator's own tests
python3 handbook/tools/gen.py check
python3 handbook/tools/gen.py build          # must produce no diff
git status --short handbook/
```

The second `build` producing a diff means the generator is not reproducible,
which CI also checks. Fix it before committing.

Then confirm at least one changed page renders correctly — Mermaid blocks and
tables are the usual casualties.

If a chapter's prose changed, look at the PDF too. `pdftotext -layout` is enough
to catch the failures that matter: markup leaking onto the page (`**`, backticks,
`](`), a table column crushed too narrow, or text running past the measure.

## Step 5 — Report

Tell the user:

- what the generated chapters gained or lost (new crates, routes, modules,
  features, configuration keys, commands);
- which prose chapters you updated and why;
- which chapters you re-baselined without changes, and on what basis you judged
  them still accurate;
- anything you could not verify, stated plainly rather than glossed over.

Commit the chapters together with `handbook/drift.lock.json` and
`handbook/handbook.pdf` — the lock is the record of what was confirmed, and it is
meaningless if it lands separately.
