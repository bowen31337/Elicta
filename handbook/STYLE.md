# Writing Contract

Rules for prose chapters. Generated chapters are the renderer's problem, not yours.

## Who you are writing for

Somebody who **uses** Elicta and does not work on it. A consultant, an analyst,
the person who administers it for a team. They are intelligent and busy, and
they have no repository, no terminal, and no interest in how it is built.

That is not a tone. It is a scope rule, and two parts of it are checked:

- **No technical description of the software.** No components, no network
  interfaces, no file layouts, no build or test commands. If a sentence only
  makes sense to somebody who has the source open, it belongs in `CLAUDE.md`
  or `docs/`, not here.
- **Explain the product by what it does on screen**, not by what happens
  underneath. "The button is unavailable until consent is confirmed" is right.
  "The consent gate is enforced in the service layer" is not.

Where something is genuinely unfinished, say so in the chapter, in the same
plain voice. A guide that describes intentions in the same tone as behaviour is
worse than no guide, because the reader cannot tell which is which.

## Structure

- **One H1 per chapter, and it matches `book.toml` exactly.** `check` enforces this.
- **Everything below `<!-- HANDBOOK-NAV -->` belongs to the generator.** Write above it. The
  marker and everything after it is rewritten on every build.
- **Sections are H2, subsections H3.** Deeper than H3 means the chapter should be split.
- **Chapters end where they end.** No summary section restating what was just said.

## Voice

- **Say what is true, including when it is unflattering.** "Formatting is not gated; the tree
  carries 328 pre-existing hunks" is a useful sentence. "Formatting is handled separately" is
  not.
- **Prefer the concrete.** Name the file, the function, the flag, the number. A reader who
  cannot act on a paragraph will skip the next one.
- **Explain the why once.** A rule with no reason gets worked around the first time it is
  inconvenient.
- **No hedging as decoration.** "It is generally recommended that one should consider" is
  four words of throat-clearing around "do".
- **Second person for instructions, third for description.** "Run `build`" and "`build`
  rewrites the index" — not "we run" or "one runs".
- **British or American spelling: pick one per chapter and be consistent.** The existing
  chapters use British.

## Write for somebody who does not work here

This handbook is read outside the team, as one bound document, often on paper.
Two rules follow, and both are checked automatically.

- **Never send the reader elsewhere.** No links to other chapters, no links to
  files in the repository. They are dead ends for somebody holding a printout.
  Say the thing where the reader is standing, even at the cost of repeating it.
- **Never cite a number they cannot resolve.** No requirement identifiers, no
  architecture section numbers, no decision-record numbers. State the
  requirement in words.

Beyond what the checks can see: prefer the plain word. Write "reachable from the
running application", not "mounted". Where a technical term really is the
clearest thing to say, say it and explain it once, in the sentence where it first
appears. Assume the reader is intelligent and busy, not that they are an
engineer.

## Screenshots

Show the screen. A chapter about something the reader will look at should
contain a picture of it:

```markdown
![What the caption says](../../docs/journeys/screenshots/panel-asked-it.png)
```

A line that is nothing but a picture becomes a picture; a picture mentioned
inside a sentence stays inside the sentence. Captions are sentences, not labels
— say what the reader should notice, not what the file is called.

Blank space at the foot of a screenshot is cropped automatically, and a picture
taller than it is wide is held back from the full text width. You do not need to
size anything.

## Diagrams

Draw the things that have no screen. A diagram belongs in a `diagram` block,
which the generator renders as an actual picture:

- `steps` — a numbered sequence, each stage with a sentence or two
- `flow` — a short chain with arrows
- `timeline` — where the time goes, drawn to scale
- `compare` — two options, row by row
- `stack` — layers or labelled parts

Keep item text short enough to read at a glance; a diagram carrying a paragraph
per row is a table wearing a costume. Do not use mermaid in new chapters — it
renders on a code-hosting site but not in the bound document, which is the wrong
way round.

## Claims

- **Every claim about the code must be checkable.** If you cannot point at the file, do not
  write the sentence.
- **State what you did not verify.** "I could not confirm X" is worth more than a confident
  guess, and costs the next reader far less.
- **`BANNED_CLAIMS` in `tools/lint.py` lists statements known to be false here.** If a
  chapter needs to quote one in order to warn about it, add
  `<!-- lint-allow: <tag> -->` to that page. Do not delete the entry.

## Links and code

- **Relative links only, and they must resolve.** `check` follows every one. Link to a
  sibling chapter as `06-wiring-a-new-feature.md`, to the index as `../index.md`, and out of
  the handbook as `../../docs/RUNBOOK.md`.
- **Code blocks carry a language.** ` ```bash `, ` ```toml `, ` ```rust `.
- **Commands are copy-pasteable as written**, from the repository root unless the block says
  otherwise.
- **Mermaid diagrams use a known type and balanced brackets.** `check` verifies both. Keep
  node labels free of parentheses and quotes; the renderers disagree about escaping.

## Tables

- **A table earns its place when there are three or more parallel items.** Two rows is a
  sentence.
- **Escape pipes as `&#124;`.** A backslash-escaped pipe is still a literal `|` in the file,
  which breaks structural checks over the table.

## What the PDF does with your Markdown

Every chapter is also typeset into `handbook.pdf`, so a few habits pay off:

- **`diagram` blocks are drawn; mermaid blocks are not.** Use the former.
- **Tables are sized to their content.** A column holding one very long cell
  squeezes its neighbours less than it used to, but a table with a
  paragraph-length cell in it still reads better as a list.
- **Long unbroken strings are broken mid-word** when they exceed the measure. A
  70-character path in running prose will look broken because it is.
- **There should be no links at all in a chapter.** See the rule above.

## Length

A chapter that has grown past roughly 250 lines is doing two jobs. Split it and add the entry
to `book.toml` — including its `watches`, or drift detection will not cover the new half.
