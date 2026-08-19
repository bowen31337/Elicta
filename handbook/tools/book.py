"""The chapter manifest: `handbook/book.toml`, loaded and validated.

The manifest is the single list of chapters. Both `build` and `check` read
it, so a chapter that exists on disk but not here -- or here but not on
disk -- is an error rather than a page nobody ever links to.

TOML, not YAML, so the generator runs on `tomllib` from the standard
library and the handbook needs no dependencies of its own.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import generators

MANIFEST = "handbook/book.toml"
KINDS = ("prose", "generated")


class ManifestError(Exception):
    """The manifest is malformed. Always names the offending chapter."""


@dataclass(frozen=True)
class Chapter:
    id: str
    file: str
    title: str
    kind: str
    generator: str = ""
    summary: str = ""
    part: str = ""
    watches: list[str] = field(default_factory=list)

    @property
    def basename(self) -> str:
        return Path(self.file).name

    def path(self, root: Path) -> Path:
        return Path(root) / "handbook" / self.file


@dataclass(frozen=True)
class Book:
    title: str
    intro: str
    chapters: list[Chapter]

    def by_id(self, chapter_id: str) -> Chapter:
        for chapter in self.chapters:
            if chapter.id == chapter_id:
                return chapter
        raise KeyError(chapter_id)


def load_book(root: Path) -> Book:
    manifest = Path(root) / MANIFEST
    if not manifest.is_file():
        raise ManifestError(f"no manifest at {MANIFEST}")
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    meta = data.get("handbook", {})
    chapters: list[Chapter] = []
    seen: set[str] = set()
    for entry in data.get("chapter", []):
        chapter = _chapter(entry)
        if chapter.id in seen:
            raise ManifestError(f"duplicate chapter id {chapter.id!r}")
        seen.add(chapter.id)
        chapters.append(chapter)
    if not chapters:
        raise ManifestError("the manifest lists no chapters")
    return Book(
        title=meta.get("title", "Handbook"),
        intro=meta.get("intro", ""),
        chapters=chapters,
    )


def _chapter(entry: dict) -> Chapter:
    for required in ("id", "file", "title", "kind"):
        if required not in entry:
            raise ManifestError(f"chapter {entry.get('id', entry)!r} is missing {required!r}")
    kind, chapter_id = entry["kind"], entry["id"]
    if kind not in KINDS:
        raise ManifestError(f"chapter {chapter_id!r} has unknown kind {kind!r}")
    generator = entry.get("generator", "")
    if kind == "generated":
        if not generator:
            raise ManifestError(f"generated chapter {chapter_id!r} names no generator")
        if generator not in generators.GENERATORS:
            known = ", ".join(sorted(generators.GENERATORS))
            raise ManifestError(
                f"chapter {chapter_id!r} names unknown generator {generator!r}; known: {known}"
            )
    elif generator:
        raise ManifestError(f"prose chapter {chapter_id!r} may not name a generator")
    return Chapter(
        id=chapter_id,
        file=entry["file"],
        title=entry["title"],
        kind=kind,
        generator=generator,
        summary=entry.get("summary", ""),
        part=entry.get("part", ""),
        watches=list(entry.get("watches", [])),
    )
