"""Pure rendering: facts in, Markdown out.

Nothing here reads the filesystem or knows where a chapter lives. That is
what lets `build` be reproducible -- CI runs it a second time and requires
no diff, which only holds if rendering is a function of its inputs alone.

Two conventions carry the whole scheme:

* `GENERATED_MARKER` opens every machine-written page. `build` overwrites
  those files wholesale and never opens a prose chapter for writing.
* `NAV_MARKER` divides a prose chapter into the half a human owns (above)
  and the half `build` owns (below).
"""

from __future__ import annotations

import re

GENERATED_MARKER = "<!-- HANDBOOK-GENERATED: do not edit by hand -->"
NAV_MARKER = "<!-- HANDBOOK-NAV -->"

#: Shown where a source offers no description. Never replaced with a guess.
NO_DOC = "_no module doc_"

#: Shown when a reader finds nothing at all -- an empty chapter is a signal,
#: not a formatting problem, so it says so in the page.
EMPTY_NOTICE = "_Nothing found. That is a gap in the source, not in the handbook._"

BUILD_CMD = "python3 handbook/tools/gen.py build"


#: Citations inside a doc comment, which mean nothing to a reader holding
#: only the handbook.
_ID = r"(?:PRD\s+)?(?:FR|NFR|ADR)-[\d.]+"
_SECTION = r"§\s?[\d.]+"
_CITATION = rf"(?:architecture\s+)?{_ID}|architecture\s+{_SECTION}|{_SECTION}"

_PAREN_CITATION_RE = re.compile(r"\s*\([^()]*?(?:" + _CITATION + r")[^()]*?\)")
# The leading comma stays and the trailing one goes, so "on a tick, per
# FR-5.10, without blocking" keeps exactly one comma rather than none.
_INLINE_ID_RE = re.compile(r"\s*(?:per|see|as required by)\s+(?:" + _ID + r")\b,?")
# A section reference carrying the sentence's subject -- "Architecture §6's
# concurrency table" -- cannot be deleted without leaving a fragment, so it
# is replaced by the document it names.
_NAMED_SECTION_RE = re.compile(r"(?i:architecture)\s+" + _SECTION)
# `\b` does not work before `§`, which is not a word character.
_BARE_SECTION_RE = re.compile(r"\s*" + _SECTION + r"(?![\w])")
_BARE_ID_RE = re.compile(r"\s*(?<![\w-])(?:" + _ID + r")(?![\w-])")


def plain_summary(text: str) -> str:
    """Drop internal citations from text lifted out of the code.

    A doc comment writes "(architecture §3; PRD FR-8.2)" for the engineer
    who has those documents open. In the handbook it is noise at best, and
    at worst it sends a reader looking for something they do not have.

    Most citations are simply removed. One kind is replaced instead: a
    possessive like "Architecture §6's concurrency table" is carrying the
    subject of its sentence, and deleting it leaves a fragment. The full
    wording is still in the source either way.
    """
    if not text:
        return text
    cleaned = _PAREN_CITATION_RE.sub("", text)
    cleaned = _INLINE_ID_RE.sub("", cleaned)

    def name_it(match: re.Match) -> str:
        # Keep the capitalisation the citation had, so a reference that
        # opened a sentence still opens one.
        article = "The" if match.group(0)[0].isupper() else "the"
        return f"{article} architecture document"

    cleaned = _NAMED_SECTION_RE.sub(name_it, cleaned)
    cleaned = _BARE_SECTION_RE.sub("", cleaned)
    cleaned = _BARE_ID_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip()


def cell(text: str) -> str:
    """Make text safe inside a Markdown table cell.

    Pipes become the HTML entity rather than a backslash escape: an escaped
    pipe is still a literal `|` in the file, which makes column counting --
    and therefore any structural check over the table -- unreliable.
    """
    return (text or "").replace("|", "&#124;").replace("\n", " ").strip()


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return out


def generated_page(title: str, source_paths: list[str], body: list[str]) -> str:
    sources_note = ", ".join(source_paths)
    lines = [
        GENERATED_MARKER,
        # Provenance for whoever maintains the guide, kept out of the reader's
        # way: a file path means nothing to somebody using the product.
        f"<!-- built from: {sources_note} -->",
        "",
        f"# {title}",
        "",
        "> This page is assembled automatically every time this guide is made,",
        "> from notes kept alongside the product itself, so it cannot fall out of date.",
        "> Editing it by hand has no effect — the next build puts it back.",
        "",
        *body,
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ── Bodies ───────────────────────────────────────────────────────────────


def crate_body(crates) -> list[str]:
    if not crates:
        return [EMPTY_NOTICE]
    out: list[str] = []
    for tier, heading, lead in (
        ("plugin", "On the fast path",
         "These are the components that have to answer inside a tenth of a "
         "second. Each one has to be named on a single list before the running "
         "application can reach it; a component that is present in the folder "
         "but missing from that list is unreachable, and does nothing."),
        ("shared", "Shared building blocks",
         "Used by the components above rather than reached directly."),
    ):
        tier_crates = [c for c in crates if c.tier == tier]
        if not tier_crates:
            continue
        out += [f"## {heading}", ""]
        if tier == "plugin":
            mounted = sum(1 for c in tier_crates if c.mounted)
            out += [f"{mounted} of {len(tier_crates)} are reachable. {lead}", ""]
        else:
            out += [lead, ""]
        rows = []
        for crate in tier_crates:
            if tier == "plugin":
                status = "yes" if crate.mounted else "**no — unreachable**"
            else:
                status = "—"
            rows.append([f"`{crate.name}`", f"`{crate.path}`", status,
                         plain_summary(crate.doc) or NO_DOC])
        out += table(["Component", "Where it lives", "Reachable", "What it does"],
                     rows) + [""]
    return out


def route_body(routes) -> list[str]:
    if not routes:
        return [EMPTY_NOTICE]
    tags = sorted({r.tag for r in routes})
    out = [
        f"The service answers on {len(routes)} addresses, grouped below by the "
        f"part of the product they belong to.",
        "",
        "Read from the description the running service publishes about itself, "
        "rather than from any list kept by hand.",
        "",
    ]
    for tag in tags:
        out += [f"### {tag}", ""]
        rows = [[f"`{r.method}`", f"`{r.path}`", plain_summary(r.summary)]
                for r in routes if r.tag == tag]
        out += table(["Kind", "Address", "What it does"], rows) + [""]
    return out


def env_body(env) -> list[str]:
    if not env:
        return [EMPTY_NOTICE]
    groups = {
        marker: [v for v in env if v.marker == marker]
        for marker in ("required", "optional", "unmarked")
    }
    out = [
        ", ".join(f"{len(vars_)} {name}" for name, vars_ in groups.items() if vars_) + ".",
        "Defaults and worked examples stay in `.env.example`; this page is the index.",
        "",
    ]
    for marker, heading, lead in (
        ("required", "Required",
         "Without one of these, the part of the product that needs it refuses to "
         "start and says which one is missing, rather than failing later in a way "
         "that looks like something else."),
        ("optional", "Optional", "Every one of these has a working default."),
        ("unmarked", "Unmarked",
         "The settings file says every entry is marked as required or optional. "
         "These carry neither mark, so whether they are needed is written down "
         "nowhere. Adding the missing mark moves them into the right group above."),
    ):
        group = groups[marker]
        if not group:
            continue
        out += [f"## {heading}", "", lead, ""]
        rows = [[f"`{v.name}`", plain_summary(v.section) or "—",
                 plain_summary(v.summary) or NO_DOC]
                for v in group]
        out += table(["Variable", "Section", "What it is"], rows) + [""]
    return out


def component_body(components, lead: str) -> list[str]:
    if not components:
        return [EMPTY_NOTICE]
    out = [f"{len(components)} in total. {lead}", ""]
    rows = []
    for comp in components:
        notes = []
        if not comp.importable:
            notes.append("name contains a hyphen, so it can only be loaded indirectly")
        if not comp.is_package and comp.kind == "service module":
            notes.append("**missing its `__init__.py`**, so nothing will find it")
        rows.append([f"`{comp.name}`", f"`{comp.path}`", str(comp.files),
                     "; ".join(notes) or "—"])
    out += table(["Name", "Path", "Files", "Notes"], rows) + [""]
    return out


def command_body(commands) -> list[str]:
    if not commands:
        return [EMPTY_NOTICE]
    out = [f"{len(commands)} shortcut commands, checked in alongside the code so "
           f"that everyone working on it has the same ones.", ""]
    rows = [[f"`/{c.name}`", c.title, plain_summary(c.summary)] for c in commands]
    out += table(["Command", "Title", "What it does"], rows) + [""]
    return out


def readiness_body(notes) -> list[str]:
    """What works today, read from the notes kept beside the product.

    A guide that describes intentions in the same voice as behaviour is
    worse than no guide: the reader cannot tell which is which. So this
    page is assembled from the status notes rather than written, and it
    leads with what works because that is what most readers came for.
    """
    if not notes:
        return [EMPTY_NOTICE]
    working = [n for n in notes if n.state == "working"]
    out = [
        f"{len(notes)} notes in total, {len(working)} of them describing "
        f"something that works today.",
        "",
        "This page is read from the notes kept alongside each part of the "
        "product, so it says what is true now rather than what was true when "
        "somebody last remembered to update a page.",
        "",
    ]
    for state, heading, lead in (
        ("working", "Working today",
         "You can rely on these."),
        ("setup", "Needs setting up first",
         "These work, once somebody has configured the outside service they "
         "depend on."),
        ("planned", "Still to come",
         "These are described elsewhere in this guide as things that are not "
         "finished. They are listed together here so that nobody has to hunt "
         "for the caveats."),
    ):
        group = [note for note in notes if note.state == state]
        if not group:
            continue
        out += [f"## {heading}", "", lead, ""]
        rows = [[note.area, note.note] for note in group]
        out += table(["Part of the product", "What the note says"], rows) + [""]
    return out


# ── Navigation ───────────────────────────────────────────────────────────


def apply_nav(text: str, prev, next) -> str:
    """Rewrite the generated footer of a prose chapter, in place.

    Everything above `NAV_MARKER` is returned untouched, so a human's prose
    is never at risk. Everything from the marker down is replaced, which is
    what stops a re-run from stacking a second footer.
    """
    body = text.split(NAV_MARKER)[0].rstrip()
    links = []
    if prev:
        links.append(f"← [{prev[1]}]({prev[2]})")
    links.append("[Contents](../index.md)")
    if next:
        links.append(f"[{next[1]}]({next[2]}) →")
    return "\n".join([body, "", NAV_MARKER, "", "---", "", " · ".join(links), ""])
