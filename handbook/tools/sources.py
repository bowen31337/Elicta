"""Readers that turn repository files into facts the handbook can render.

Every function here is a pure read: it takes a repo root and returns plain
data. Nothing in this module writes, formats, or knows about Markdown --
that separation is what makes `render.py` testable without a repo and this
module testable without a renderer.

The rule these readers follow: report what is there, never fill a gap. A
crate with no module doc gets an empty summary, and the chapter shows the
gap. Inventing a plausible sentence would make the handbook a worse source
of truth than the code it describes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import drift

# ── Crates ───────────────────────────────────────────────────────────────

#: Where the two crate tiers live, in the order chapters present them.
CRATE_TIERS = (("plugin", "core/crates"), ("shared", "core/shared"))

#: The seam that decides which plugin crates are actually reachable.
REGISTRY = "core/shared/app/src/registry.rs"

_MOUNTED_RE = re.compile(r"MOUNTED_CRATES[^=]*=\s*&\[(.*?)\]", re.S)
_RUSTDOC_LINK_RE = re.compile(r"\[(`[^`\]]+`)\]")


@dataclass(frozen=True)
class Crate:
    name: str
    tier: str
    path: str
    mounted: bool
    doc: str


def _module_doc(lib_rs: Path) -> str:
    """The crate's first `//!` paragraph, as one line of prose."""
    if not lib_rs.is_file():
        return ""
    lines: list[str] = []
    for raw in lib_rs.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("//!"):
            break
        body = line[3:].strip()
        if not body:  # blank doc line ends the first paragraph
            break
        lines.append(body)
    # Rustdoc intra-doc links are not Markdown links; unwrap them so the
    # chapter does not render a link that points nowhere.
    return _RUSTDOC_LINK_RE.sub(r"\1", " ".join(lines))


def mounted_crate_names(root: Path) -> list[str]:
    """The crate names listed in the registry seam, in mount order."""
    registry = Path(root) / REGISTRY
    if not registry.is_file():
        return []
    match = _MOUNTED_RE.search(registry.read_text(encoding="utf-8"))
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def collect_crates(root: Path) -> list[Crate]:
    root = Path(root)
    mounted = set(mounted_crate_names(root))
    crates: list[Crate] = []
    for tier, rel in CRATE_TIERS:
        base = root / rel
        if not base.is_dir():
            continue
        for manifest in sorted(base.glob("*/Cargo.toml")):
            name = manifest.parent.name
            crates.append(
                Crate(
                    name=name,
                    tier=tier,
                    path=f"{rel}/{name}",
                    mounted=name in mounted,
                    doc=_module_doc(manifest.parent / "src" / "lib.rs"),
                )
            )
    return crates


def crate_by_name(crates: list[Crate], name: str) -> Crate:
    for crate in crates:
        if crate.name == name:
            return crate
    raise KeyError(name)


# ── HTTP routes ──────────────────────────────────────────────────────────

#: `packages/api-client/openapi.json` is generated from the live service, so
#: it is the honest route table -- `FastAPI.routes` under-reports here.
OPENAPI = "packages/api-client/openapi.json"

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    summary: str
    tag: str


def collect_routes(root: Path) -> list[Route]:
    schema_file = Path(root) / OPENAPI
    if not schema_file.is_file():
        return []
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    routes: list[Route] = []
    for path, operations in schema.get("paths", {}).items():
        for verb, operation in operations.items():
            method = verb.upper()
            if method not in _METHODS:
                continue  # `parameters`, `servers` and friends are not routes
            tags = operation.get("tags") or ["untagged"]
            routes.append(
                Route(
                    method=method,
                    path=path,
                    summary=operation.get("summary", ""),
                    tag=tags[0],
                )
            )
    return sorted(routes, key=lambda r: (r.path, r.method))


# ── Environment variables ────────────────────────────────────────────────

#: CLAUDE.md names this the source of truth for configuration names.
ENV_EXAMPLE = ".env.example"

_SECTION_RE = re.compile(r"^#\s*[─-]{2,}\s*(.+?)\s*[─-]{2,}\s*$")
_SET_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
# A commented-out variable, not prose that happens to contain an `=`: the
# value must be a single token running to end of line.
_COMMENTED_RE = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=(\S*)\s*$")
_MARKER_RE = re.compile(r"^(REQUIRED|OPTIONAL)\b\s*(\([^)]*\))?\s*[.:,—–-]*\s*")


@dataclass(frozen=True)
class EnvVar:
    name: str
    section: str
    default: str
    summary: str
    commented: bool
    #: "required", "optional", or "unmarked". `.env.example` promises every
    #: variable carries one of the first two; several carry neither, and the
    #: handbook shows that rather than picking one on the author's behalf.
    marker: str

    @property
    def required(self) -> bool:
        return self.marker == "required"


def _summarise(block: list[str]) -> tuple[str, str]:
    text = " ".join(part.strip() for part in block).strip()
    if re.search(r"\bREQUIRED\b", text):
        marker = "required"
    elif re.search(r"\bOPTIONAL\b", text):
        marker = "optional"
    else:
        marker = "unmarked"
    return marker, _MARKER_RE.sub("", text).strip()


def collect_env_vars(root: Path) -> list[EnvVar]:
    env_file = Path(root) / ENV_EXAMPLE
    if not env_file.is_file():
        return []
    section = ""
    # The marker last stated in this section. `.env.example` writes one
    # "OPTIONAL — all default if unset." above a run of variables and expects
    # it to cover the run, so a variable with no comment of its own inherits
    # it. A new section heading clears it.
    section_marker = "unmarked"
    block: list[str] = []
    seen: set[str] = set()
    found: list[EnvVar] = []
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            block = []
            continue
        heading = _SECTION_RE.match(line)
        if heading:
            section, block, section_marker = heading.group(1), [], "unmarked"
            continue
        match = _SET_RE.match(line) or _COMMENTED_RE.match(line)
        if match:
            name, value = match.group(1), match.group(2)
            if name not in seen:
                seen.add(name)
                marker, summary = _summarise(block)
                if marker == "unmarked":
                    marker = section_marker
                else:
                    section_marker = marker
                found.append(
                    EnvVar(
                        name=name,
                        section=section,
                        default=value,
                        summary=summary,
                        commented=line.startswith("#"),
                        marker=marker,
                    )
                )
            block = []
            continue
        if line.startswith("#"):
            block.append(line.lstrip("#").strip())
    return found


# ── Service modules and desktop features ─────────────────────────────────

SERVICE_MODULES = "apps/service/src/app/modules"
DESKTOP_FEATURES = "apps/desktop/src/features"


@dataclass(frozen=True)
class Component:
    name: str
    kind: str
    path: str
    is_package: bool
    importable: bool
    files: int


def _source_file_count(directory: Path) -> int:
    """Files a person wrote, not files a build produced.

    Counting build output would make the chapter go stale on a `pytest` run,
    and a check that fails on changes nobody made gets switched off.
    """
    return sum(
        1
        for path in directory.rglob("*")
        if path.is_file()
        and not any(part in drift.IGNORED_DIRS for part in path.parts)
        and path.suffix not in drift.IGNORED_SUFFIXES
    )


def _components(root: Path, rel: str, kind: str) -> list[Component]:
    base = Path(root) / rel
    if not base.is_dir():
        return []
    found: list[Component] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("__") or child.name.startswith("."):
            continue
        found.append(
            Component(
                name=child.name,
                kind=kind,
                path=f"{rel}/{child.name}",
                is_package=(child / "__init__.py").is_file(),
                # A hyphenated directory is only reachable through
                # importlib.import_module -- a literal import is a SyntaxError.
                importable=child.name.isidentifier(),
                files=_source_file_count(child),
            )
        )
    return found


def collect_service_modules(root: Path) -> list[Component]:
    return _components(root, SERVICE_MODULES, "service module")


def collect_desktop_features(root: Path) -> list[Component]:
    return _components(root, DESKTOP_FEATURES, "desktop feature")


# ── Slash commands ───────────────────────────────────────────────────────

COMMANDS = ".claude/commands"


@dataclass(frozen=True)
class Command:
    name: str
    title: str
    summary: str
    path: str


def collect_commands(root: Path) -> list[Command]:
    base = Path(root) / COMMANDS
    if not base.is_dir():
        return []
    found: list[Command] = []
    for doc in sorted(base.glob("*.md")):
        title, summary = "", ""
        for raw in doc.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#") and not title:
                title = line.lstrip("#").strip()
            elif not line.startswith("#") and title and not summary:
                summary = line
                break
        found.append(
            Command(name=doc.stem, title=title or doc.stem, summary=summary,
                    path=f"{COMMANDS}/{doc.name}")
        )
    return found


# ── Readiness, from the journey documents ────────────────────────────────

JOURNEYS = "docs/journeys"

#: Each journey ends with a table saying honestly what works. The markers
#: are emoji, which no PDF font here can draw, so they become words at the
#: point of reading rather than being carried around and dropped later.
_STATES = {"\u2705": "working", "\u23f3": "planned", "\u2699": "setup"}

_STATUS_HEADING_RE = re.compile(r"^##\s+Where this stands\s*$", re.M)
_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", re.M)
_TITLE_RE = re.compile(r"^#\s+(?:\d+\.\s*)?(.+?)\s*$", re.M)


@dataclass(frozen=True)
class UnknownStatusMarker:
    #: Repo-relative path of the journey the row is in.
    document: str
    #: The marker cell as written, so the message can quote it back.
    marker: str


@dataclass(frozen=True)
class ReadinessNote:
    #: The journey this came from, without its number.
    area: str
    #: "working", "planned" or "setup".
    state: str
    note: str


def _status_rows(root: Path):
    """Every row of every journey's status table, with its journey."""
    base = Path(root) / JOURNEYS
    if not base.is_dir():
        return
    for document in sorted(base.glob("*.md")):
        if document.name.upper().startswith("README"):
            continue
        text = document.read_text(encoding="utf-8")
        heading = _STATUS_HEADING_RE.search(text)
        if not heading:
            continue
        title = _TITLE_RE.search(text)
        area = title.group(1) if title else document.stem
        for marker, note in _ROW_RE.findall(text[heading.end():]):
            yield document, area, marker, note


def _state_of(marker: str) -> str:
    return next((name for symbol, name in _STATES.items() if symbol in marker), "")


def unknown_status_markers(root: Path) -> list[UnknownStatusMarker]:
    """Status rows carrying a marker none of the three states recognise.

    `collect_readiness` skips such a row, and so does the header row and the
    `|---|` separator — which means an unrecognised marker is indistinguishable
    from table furniture and vanishes from the handbook in silence. It has
    happened: a "not yet" row written with a construction emoji rather than the
    hourglass simply was not there afterwards, and nothing said so.

    Reported rather than raised, so one mistyped emoji names itself instead of
    stopping the whole build.
    """
    found: list[UnknownStatusMarker] = []
    for document, _area, marker, note in _status_rows(root):
        if _state_of(marker) or set(note) <= set("- "):
            continue
        if not any(character > "\u2000" for character in marker):
            continue      # a plain-text cell: the table's own header row
        found.append(UnknownStatusMarker(
            # Repo-relative, like every other finding's location, so the
            # message is the same length whoever's machine printed it.
            document=Path(document).relative_to(Path(root)).as_posix(),
            marker=marker,
        ))
    return found


def collect_readiness(root: Path) -> list[ReadinessNote]:
    found: list[ReadinessNote] = []
    for _document, area, marker, note in _status_rows(root):
        state = _state_of(marker)
        if not state or set(note) <= set("- "):
            continue      # the table's own separator row
        found.append(ReadinessNote(area=area, state=state, note=note))
    return found
