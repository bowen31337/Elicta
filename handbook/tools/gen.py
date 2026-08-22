#!/usr/bin/env python3
"""The handbook generator.

    python3 handbook/tools/gen.py build     # regenerate chapters and the PDF
    python3 handbook/tools/gen.py check     # errors block CI, warnings ask
    python3 handbook/tools/gen.py status    # what is generated, what drifted
    python3 handbook/tools/gen.py pdf       # rebuild the PDF on its own
    python3 handbook/tools/gen.py accept --chapter <id>

Standard library only, on purpose. A documentation tool that needs its own
dependency resolution before it can tell you the docs are stale is a tool
people stop running.

The division of labour: `build` owns every byte of a generated chapter and
the footer of a prose chapter, and nothing else. `check` re-derives what
`build` would write and fails if the file on disk disagrees -- which is how
a feature that lands without a handbook pass gets caught.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import book
import drift
import generators
import lint
import render
import sources
import typeset

ROOT = Path(__file__).resolve().parents[2]

STUB_MARKER = "<!-- HANDBOOK-STUB: this chapter has not been written yet -->"

#: Handbook Markdown that is not a chapter and never appears in book.toml.
NON_CHAPTERS = {"index.md", "README.md", "STYLE.md"}

#: The whole handbook as one bound document, beside the chapters it is
#: built from.
PDF_NAME = "handbook.pdf"

#: The modules whose output the PDF is. A layout change has to invalidate
#: the committed file, or it keeps the old typesetting for ever.
PDF_TOOL_SOURCES = ("pdf.py", "mdread.py", "typeset.py")

_DIGEST_RE = re.compile(rb"/SourceDigest \(([0-9a-f]+)\)")


def pdf_path(root: Path) -> Path:
    return Path(root) / "handbook" / PDF_NAME


def pdf_source_digest(root: Path) -> str:
    """Digest of everything the PDF is a function of.

    Two parts, because they live in different places: the content (the
    manifest and the chapters, under `root`) and the code that renders it
    (this directory, wherever the tools happen to be checked out).
    """
    content = drift.digest(root, ["handbook/book.toml", "handbook/chapters"])
    tools = drift.digest(Path(__file__).resolve().parent, list(PDF_TOOL_SOURCES))
    return hashlib.sha256(f"{content}:{tools}".encode()).hexdigest()


def embedded_digest(path: Path) -> str | None:
    """The digest a built PDF records, or None if there is no PDF."""
    if not Path(path).is_file():
        return None
    match = _DIGEST_RE.search(Path(path).read_bytes())
    return match.group(1).decode() if match else None


def write_pdf(root: Path, loaded: book.Book, digest: str) -> tuple[int, int]:
    data = typeset.render_pdf(root, loaded, digest)
    pdf_path(root).write_bytes(data)
    pages = data.count(b"/Type /Page\n") or data.count(b"/Type /Page ")
    return len(data), pages


# ── Deriving the expected content of every page ──────────────────────────


def _stub(chapter: book.Chapter) -> str:
    return "\n".join([
        f"# {chapter.title}",
        "",
        STUB_MARKER,
        "",
        f"> **Not written yet.** {chapter.summary or 'No summary in book.toml.'}",
        ">",
        "> Scaffolded by `python3 handbook/tools/gen.py build`. Write the chapter",
        "> here, then delete the stub marker above.",
        "",
    ])


def _neighbours(chapters: list[book.Chapter], index: int):
    def link(chapter):
        return (chapter.id, chapter.title, chapter.basename)

    prev = link(chapters[index - 1]) if index > 0 else None
    nxt = link(chapters[index + 1]) if index + 1 < len(chapters) else None
    return prev, nxt


def expected_page(root: Path, loaded: book.Book, index: int) -> str:
    """What `build` would write for one chapter, without writing it."""
    chapter = loaded.chapters[index]
    if chapter.kind == "generated":
        generator = generators.GENERATORS[chapter.generator]
        body = generator.body(generator.collect(root))
        text = render.generated_page(chapter.title, generator.paths, body)
    else:
        path = chapter.path(root)
        text = path.read_text(encoding="utf-8") if path.is_file() else _stub(chapter)
    prev, nxt = _neighbours(loaded.chapters, index)
    return render.apply_nav(text, prev, nxt)


def expected_index(loaded: book.Book) -> str:
    body: list[str] = []
    if loaded.intro:
        body += [loaded.intro, ""]
    part = None
    rows: list[list[str]] = []

    def flush():
        if rows:
            body.extend(render.table(["Chapter", "What it covers"], list(rows)) + [""])
            rows.clear()

    for chapter in loaded.chapters:
        if chapter.part != part:
            flush()
            part = chapter.part
            if part:
                body += [f"## {part}", ""]
        kind = " *(generated)*" if chapter.kind == "generated" else ""
        rows.append([f"[{chapter.title}]({chapter.file}){kind}", chapter.summary])
    flush()
    generated = [c.id for c in loaded.chapters if c.kind == "generated"]
    body += [
        f"{len(loaded.chapters)} chapters, of which {len(generated)} are generated",
        "from the code and must never be edited by hand.",
        "",
    ]
    return render.generated_page(loaded.title, [book.MANIFEST], body)


# ── Commands ─────────────────────────────────────────────────────────────


def build(root: Path) -> int:
    loaded = book.load_book(root)
    written: list[str] = []
    for index, chapter in enumerate(loaded.chapters):
        path = chapter.path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = expected_page(root, loaded, index)
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        if existing != content:
            path.write_text(content, encoding="utf-8")
            written.append(f"handbook/{chapter.file}" + ("" if existing else "  (scaffolded)"))
    index_path = Path(root) / "handbook" / "index.md"
    index_text = expected_index(loaded)
    if not index_path.is_file() or index_path.read_text(encoding="utf-8") != index_text:
        index_path.write_text(index_text, encoding="utf-8")
        written.append("handbook/index.md")

    # After the chapters, never before: the PDF is built from what they
    # now contain.
    digest = pdf_source_digest(root)
    if embedded_digest(pdf_path(root)) != digest:
        size, pages = write_pdf(root, loaded, digest)
        written.append(f"handbook/{PDF_NAME}  ({pages} pages, {size // 1024} KB)")

    if written:
        print(f"build: rewrote {len(written)} file(s)")
        for name in written:
            print(f"  {name}")
    else:
        print("build: already up to date")
    # Deliberately does not touch drift.lock.json. Baselining is a claim
    # that a human re-read the chapter, and `build` cannot make that claim.
    return 0


def collect_findings(root: Path) -> list[lint.Finding]:
    loaded = book.load_book(root)
    found: list[lint.Finding] = []
    handbook_dir = Path(root) / "handbook"

    for index, chapter in enumerate(loaded.chapters):
        page = f"handbook/{chapter.file}"
        path = chapter.path(root)
        if not path.is_file():
            found.append(lint.Finding(
                lint.ERROR, "missing-page", page,
                "no such file; run `python3 handbook/tools/gen.py build` to scaffold it",
            ))
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected_page(root, loaded, index):
            what = "the generator would rewrite it" if chapter.kind == "generated" \
                else "its generated footer is out of date"
            found.append(lint.Finding(
                lint.ERROR, "stale-generated", page,
                f"{what}; run `python3 handbook/tools/gen.py build`",
            ))
        found += lint.check_page(page, actual, chapter.title)
        found += lint.check_links(root, page, actual)
        found += lint.check_false_claims(page, actual)
        if chapter.kind == "prose":
            # Generated chapters are exempt: their wording comes from the
            # code, and `render.plain_summary` already strips the citations
            # out of it.
            found += lint.check_references(page, actual)
        if STUB_MARKER in actual:
            found.append(lint.Finding(
                lint.WARNING, "stub-page", page, "the chapter is still a scaffold"))
        if chapter.kind == "prose" and render.GENERATED_MARKER in actual:
            found.append(lint.Finding(
                lint.ERROR, "generated-marker-in-prose", page,
                "a prose chapter carries the generated marker; build will not own this file",
            ))

    index_path = handbook_dir / "index.md"
    if not index_path.is_file():
        found.append(lint.Finding(lint.ERROR, "missing-page", "handbook/index.md",
                                  "run `python3 handbook/tools/gen.py build`"))
    else:
        index_text = index_path.read_text(encoding="utf-8")
        if index_text != expected_index(loaded):
            found.append(lint.Finding(
                lint.ERROR, "stale-generated", "handbook/index.md",
                "run `python3 handbook/tools/gen.py build`"))
        found += lint.check_links(root, "handbook/index.md", index_text)

    known = {chapter.file for chapter in loaded.chapters}
    for markdown in sorted(handbook_dir.rglob("*.md")):
        rel = markdown.relative_to(handbook_dir).as_posix()
        if rel in known or rel in NON_CHAPTERS:
            continue
        found.append(lint.Finding(
            lint.ERROR, "orphan-page", f"handbook/{rel}",
            "not listed in book.toml; add a [[chapter]] entry or delete the file",
        ))

    digest = pdf_source_digest(root)
    recorded = embedded_digest(pdf_path(root))
    if recorded is None:
        found.append(lint.Finding(
            lint.ERROR, "missing-pdf", f"handbook/{PDF_NAME}",
            "the bound PDF has not been built; run `python3 handbook/tools/gen.py build`",
        ))
    elif recorded != digest:
        found.append(lint.Finding(
            lint.ERROR, "stale-pdf", f"handbook/{PDF_NAME}",
            "built from different chapters than the ones on disk; "
            "run `python3 handbook/tools/gen.py build`",
        ))

    for unknown in sources.unknown_status_markers(root):
        found.append(lint.Finding(
            lint.ERROR, "unknown-status-marker", unknown.document,
            f"the status row marked {unknown.marker!r} uses no recognised "
            f"marker, so it is dropped from the generated chapter without "
            f"anything saying so; use one of \u2705, \u23f3 or \u2699",
        ))

    lock = drift.load_lock(root)
    for report in drift.compare(root, loaded.chapters, lock):
        if report.state == "drifted":
            found.append(lint.Finding(
                lint.WARNING, "drifted", f"chapter {report.chapter}",
                f"{', '.join(report.watches)} moved since this chapter was confirmed; "
                f"re-read it, then `gen.py accept --chapter {report.chapter}`",
            ))
        elif report.state == "unbaselined":
            found.append(lint.Finding(
                lint.WARNING, "unbaselined", f"chapter {report.chapter}",
                f"never confirmed against {', '.join(report.watches)}; "
                f"`gen.py accept --chapter {report.chapter}`",
            ))
    return found


def check(root: Path, strict: bool) -> int:
    found = collect_findings(root)
    errors = [f for f in found if f.level == lint.ERROR]
    warnings = [f for f in found if f.level == lint.WARNING]
    for finding in errors + warnings:
        print(f"{finding.level:7} {finding.code:24} {finding.page}\n"
              f"        {finding.message}")
    print(f"\ncheck: {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        return 1
    if strict and warnings:
        print("check: --strict, so warnings fail too")
        return 1
    return 0


def build_pdf(root: Path) -> int:
    loaded = book.load_book(root)
    digest = pdf_source_digest(root)
    size, pages = write_pdf(root, loaded, digest)
    print(f"pdf: handbook/{PDF_NAME} — {pages} pages, {size // 1024} KB, "
          f"digest {digest[:16]}")
    return 0


def status(root: Path) -> int:
    loaded = book.load_book(root)
    lock = drift.load_lock(root)
    states = {r.chapter: r.state for r in drift.compare(root, loaded.chapters, lock)}
    print(f"{loaded.title} — {len(loaded.chapters)} chapters\n")
    print(f"{'id':22} {'kind':10} {'drift':12} file")
    for chapter in loaded.chapters:
        print(f"{chapter.id:22} {chapter.kind:10} {states.get(chapter.id, '-'):12} "
              f"handbook/{chapter.file}")
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    print("\n" + ", ".join(f"{n} {state}" for state, n in sorted(counts.items())))
    return 0


def accept(root: Path, chapter_id: str | None, everything: bool) -> int:
    loaded = book.load_book(root)
    if not chapter_id and not everything:
        print("accept: name a chapter with --chapter <id>, or pass --all")
        return 1
    lock = drift.load_lock(root)
    if everything:
        lock = drift.baseline(root, loaded.chapters)
        print(f"accept: baselined all {len(lock)} watched chapters")
    else:
        try:
            lock = drift.accept(root, loaded.chapters, lock, chapter_id)
        except KeyError as error:
            print(f"accept: {error}")
            return 1
        print(f"accept: baselined {chapter_id}")
    drift.save_lock(root, lock)
    return 0


def main(argv: list[str] | None = None) -> int:
    # `--root` hangs off a shared parent so it is accepted on either side of
    # the subcommand; `gen.py build --root X` is what everyone types first.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(ROOT), help="repository root")

    parser = argparse.ArgumentParser(prog="gen.py", parents=[common],
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", parents=[common],
                   help="regenerate reference chapters, index and footers")
    check_parser = sub.add_parser("check", parents=[common],
                                  help="fail on errors; report warnings")
    check_parser.add_argument("--strict", action="store_true",
                              help="fail on warnings too (drift included)")
    sub.add_parser("status", parents=[common], help="chapter inventory and drift state")
    sub.add_parser("pdf", parents=[common], help="rebuild the bound PDF unconditionally")
    accept_parser = sub.add_parser("accept", parents=[common],
                                   help="record that a chapter was re-read")
    accept_parser.add_argument("--chapter")
    accept_parser.add_argument("--all", action="store_true", dest="everything")

    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "build":
            return build(root)
        if args.command == "check":
            return check(root, args.strict)
        if args.command == "status":
            return status(root)
        if args.command == "pdf":
            return build_pdf(root)
        if args.command == "accept":
            return accept(root, args.chapter, args.everything)
    except book.ManifestError as error:
        print(f"book.toml: {error}")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
