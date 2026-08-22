#!/usr/bin/env python3
"""Typeset one Markdown file as a standalone PDF.

    python3 scripts/md2pdf.py docs/quick-start.md
    python3 scripts/md2pdf.py docs/quick-start.md --out /tmp/qs.pdf

**Why this exists rather than a converter.** There is no pandoc here, no
browser, no LaTeX and no `reportlab` — CI installs Python and nothing else.
`handbook/tools/` already writes the PDF format directly for that reason, and
this is a thin front door onto the same three layers: `mdread` parses,
`typeset` lays out, `pdf` emits. A document rendered here is therefore set in
the same type, at the same measure, with the same screenshot handling as the
handbook — which matters, because the two get read side by side.

**What it is not.** It renders one file. There is no table of contents, no
title page and no cross-file linking, because those are properties of a *book*
and `handbook/tools/gen.py` is what builds the book. A document that wants
them wants to be a chapter, not a standalone.

Pictures resolve relative to the Markdown file's own directory, matching the
handbook's rule that a screenshot is named relative to the page that shows it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "handbook" / "tools"))

import mdread  # noqa: E402
import pdf  # noqa: E402
import typeset  # noqa: E402


def _title_of(blocks: list, fallback: str) -> str:
    """The document's own H1, or its filename if it has none."""

    for block in blocks:
        if isinstance(block, mdread.Heading) and block.level == 1:
            return "".join(span.text for span in block.spans)
    return fallback


def render(source: Path) -> bytes:
    """`source` as a PDF, in the handbook's type."""

    blocks = mdread.parse(source.read_text(encoding="utf-8"))
    title = _title_of(blocks, source.stem.replace("-", " ").title())

    theme = typeset.Theme()
    doc = pdf.Document(*theme.page)
    setter = typeset.Typesetter(doc, theme, book_title=title, base_dir=source.parent)
    # The running header would otherwise repeat the title on both sides of
    # every page, which reads as a mistake rather than as chrome.
    setter.chapter_title = ""
    setter.start_page()
    setter.render_blocks(blocks)

    # Section bookmarks, so a reader can move around a long guide. The
    # typesetter collected these as it went; nothing has to re-scan the file.
    for entry in setter.toc:
        doc.bookmark(entry.title, entry.page_index, entry.y + 20, level=0)

    doc.set_info(
        title=title,
        subject=f"Generated from {source.relative_to(ROOT) if source.is_relative_to(ROOT) else source.name}",
        custom={"Producer": "scripts/md2pdf.py via handbook/tools/pdf.py"},
    )
    return doc.render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the Markdown file to typeset")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where to write the PDF (default: the source with a .pdf suffix)",
    )
    args = parser.parse_args(argv)

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"no such file: {args.source}")

    destination = args.out or source.with_suffix(".pdf")
    payload = render(source)
    destination.write_bytes(payload)

    pages = payload.count(b"/Type /Page\n") or payload.count(b"/Type /Page")
    print(f"wrote {destination} ({len(payload) // 1024} KB, ~{pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
