"""Structural checks over the handbook.

Two levels, and the difference is the point:

* **error** — machine-decidable and machine-fixable. Blocks CI. A page with
  the wrong H1, a link to nowhere, a chapter that `build` would rewrite.
* **warning** — needs a human to judge. Never blocks CI. Drift is the whole
  warning category: only a person can say whether a chapter is still true
  after the code it describes moved.

If an error ever needs judgement to resolve, it is a warning wearing the
wrong label, and it will get suppressed rather than fixed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import render

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    page: str
    message: str


# ── Headings, fences and navigation ──────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _outside_fences(text: str):
    """Yield (line_no, line) for lines that are not inside a code fence.

    Without this, every `# comment` in a shell example counts as a heading.
    """
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def check_page(page: str, text: str, expected_title: str) -> list[Finding]:
    found: list[Finding] = []
    headings = [ln[2:].strip() for _, ln in _outside_fences(text) if ln.startswith("# ")]
    if not headings:
        found.append(Finding(ERROR, "no-h1", page, "the page has no H1"))
    elif len(headings) > 1:
        found.append(
            Finding(ERROR, "multiple-h1", page,
                    f"{len(headings)} H1 headings; a chapter has exactly one")
        )
    elif headings[0] != expected_title:
        found.append(
            Finding(ERROR, "title-mismatch", page,
                    f"H1 is {headings[0]!r} but book.toml says {expected_title!r}")
        )
    if text.count(render.NAV_MARKER) > 1:
        found.append(
            Finding(ERROR, "duplicate-nav", page,
                    f"{text.count(render.NAV_MARKER)} nav markers; delete everything from "
                    f"the first one and re-run build")
        )
    found += check_mermaid(page, text)
    return found


# ── Mermaid ──────────────────────────────────────────────────────────────

MERMAID_TYPES = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "gitGraph",
    "mindmap", "timeline", "quadrantChart", "requirementDiagram", "C4Context",
    "sankey-beta", "block-beta", "xychart-beta",
)

_MERMAID_BLOCK_RE = re.compile(r"^\s*```mermaid\s*$(.*?)^\s*```\s*$", re.M | re.S)


def check_mermaid(page: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    for block in _MERMAID_BLOCK_RE.findall(text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            found.append(Finding(ERROR, "mermaid-empty", page, "an empty mermaid block"))
            continue
        first = lines[0].strip()
        if not any(first.startswith(kind) for kind in MERMAID_TYPES):
            found.append(
                Finding(ERROR, "mermaid-unknown-type", page,
                        f"unknown diagram type {first.split()[0]!r}")
            )
        for opener, closer in (("[", "]"), ("(", ")"), ("{", "}")):
            if block.count(opener) != block.count(closer):
                found.append(
                    Finding(ERROR, "mermaid-unbalanced", page,
                            f"{block.count(opener)} {opener!r} against "
                            f"{block.count(closer)} {closer!r}")
                )
    return found


# ── Links ────────────────────────────────────────────────────────────────

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_EXTERNAL = ("http://", "https://", "mailto:", "#", "tel:")


def check_links(root: Path, page: str, text: str) -> list[Finding]:
    """Every relative link must resolve to a file that exists on disk."""
    found: list[Finding] = []
    page_dir = (Path(root) / page).parent
    for target in _LINK_RE.findall(text):
        if target.startswith(_EXTERNAL):
            continue
        resolved = (page_dir / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            found.append(Finding(ERROR, "dead-link", page, f"{target} does not exist"))
    return found


# ── Claims this repository knows to be untrue ────────────────────────────


@dataclass(frozen=True)
class Claim:
    tag: str
    pattern: str
    why: str


#: Statements that read as plausible, appear in this repo's older docs, and
#: are false. A chapter may still *warn* readers about one -- that is what
#: `<!-- lint-allow: <tag> -->` is for. Deleting an entry to make the check
#: pass is never the fix; deleting it because someone implemented the thing,
#: verified in the source, is.
BANNED_CLAIMS: tuple[Claim, ...] = (
    Claim(
        "run-sh",
        r"\./run\.sh",
        "run.sh is boilerplate from another project: it references frontend/, "
        "backend/, main.py and a trading daemon, none of which exist here.",
    ),
    Claim(
        "fmt-gated",
        # The negative lookahead matters: the chapter that states the truth --
        # that formatting is *not* gated -- must not fail the check that
        # exists to stop the opposite claim.
        r"(?i)\b(formatting|rustfmt|cargo fmt|ruff format)\b(?![^.\n]*\bnot\b)"
        r"[^.\n]{0,40}\b(gated|enforced|checked in CI|blocks CI)",
        "Formatting is not gated. cargo fmt --check reports 328 pre-existing "
        "hunks and ruff format --check 94 files; both are deferred.",
    ),
    Claim(
        "app-routes",
        r"\bapp\.routes\b(?![^\n]*under-report)",
        "FastAPI.routes under-reports here: included routers are wrapped in "
        "_IncludedRouter objects with no .path. Count app.openapi()['paths'].",
    ),
    Claim(
        "hyphen-import",
        r"(?m)^\s*(?:from|import)\s+[\w.]*(?:asr-record|slow-lane|live-session)\b",
        "Hyphenated service module dirs are only reachable via "
        "importlib.import_module; a literal import is a SyntaxError.",
    ),
    Claim(
        "pytest-root",
        r"(?i)run(?:ning)? `?pytest`?[^.\n]{0,30}\bfrom the (?:repo(?:sitory)? )?root",
        "pytest testpaths is apps/service/src. Running it from the repo root "
        "collects nothing; the e2e suites need an explicit path and --project.",
    ),
    Claim(
        "uv-run-handbook",
        r"uv run (?:--\S+ \S+ )?python handbook/",
        "There is no root pyproject.toml, so `uv run` has no project here. "
        "The handbook generator is stdlib-only: run it with python3.",
    ),
    Claim(
        "mkdocs",
        r"(?i)\bmkdocs\b",
        "mkdocs is not a dependency of this repo and no mkdocs.yml is "
        "generated. The handbook is plain Markdown with a generated index.",
    ),
    Claim(
        "zh-edition",
        r"handbook/zh/|Chinese edition",
        "The handbook is English-only. There is no handbook/zh/ tree.",
    ),
)

_ALLOW_RE = re.compile(r"<!--\s*lint-allow:\s*([^>]+?)\s*-->")


# ── Sending the reader somewhere else ────────────────────────────────────

#: Citations that mean nothing to a reader who has only the handbook: a
#: requirement number, an architecture section, a decision record, or a
#: document named by its initials.
_SPEC_RE = re.compile(
    r"\b(?:FR|NFR|ADR)-\d"      # FR-5.4, NFR-3.1, ADR-012
    r"|§\s*\d"                  # architecture §3.7
    r"|\b(?:PRD|BMAD)\b"        # documents named by their initials
)
_CODE_SPAN_RE = re.compile(r"`+[^`\n]*`+")


def allowed_tags(text: str) -> set[str]:
    return {tag.strip() for group in _ALLOW_RE.findall(text) for tag in group.split(",")}


def check_references(page: str, text: str) -> list[Finding]:
    """Prose must stand on its own.

    The handbook is read as one bound document by people outside the team.
    "See chapter 6" is a dead end on paper, and "as FR-5.4 requires" names
    something the reader cannot look up. Say the thing instead.
    """
    # Everything below the marker is the generated footer -- links `build`
    # wrote, which the PDF drops anyway. Only what an author typed counts.
    text = text.split(render.NAV_MARKER)[0]
    allowed = allowed_tags(text)
    found: list[Finding] = []

    if "cross-reference" not in allowed:
        for match in _LINK_RE.finditer(text):
            target = match.group(1)
            if target.startswith(_EXTERNAL):
                continue
            if match.start() > 0 and text[match.start() - 1] == "!":
                continue        # a picture is content, not a pointer
            label = re.match(r"\[([^\]]*)\]", match.group(0))
            name = label.group(1) if label else target
            found.append(Finding(
                ERROR, "cross-reference", page,
                f"links to {target} for {name!r}; the handbook is read as one "
                f"document, so say what the reader needs here instead",
            ))

    if "spec-reference" not in allowed:
        # Code spans are quoting the source, not addressing the reader.
        prose = _CODE_SPAN_RE.sub(" ", text)
        seen: set[str] = set()
        for match in _SPEC_RE.finditer(prose):
            token = match.group(0)
            if token in seen:
                continue
            seen.add(token)
            found.append(Finding(
                ERROR, "spec-reference", page,
                f"cites {token!r}, which the reader cannot look up; state the "
                f"requirement in words",
            ))
    return found


def check_false_claims(page: str, text: str) -> list[Finding]:
    allowed = {
        tag.strip()
        for group in _ALLOW_RE.findall(text)
        for tag in group.split(",")
    }
    found: list[Finding] = []
    for claim in BANNED_CLAIMS:
        if claim.tag in allowed:
            continue
        if re.search(claim.pattern, text):
            found.append(
                Finding(
                    ERROR, "false-claim", page,
                    f"{claim.tag}: {claim.why} If the page is warning readers about "
                    f"this, add <!-- lint-allow: {claim.tag} -->.",
                )
            )
    return found
