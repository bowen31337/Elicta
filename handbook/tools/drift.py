"""Drift detection: has the code a hand-written chapter describes moved?

Generated chapters need none of this -- `build` rebuilds them and `check`
compares bytes. Prose cannot be rebuilt, so each prose chapter declares the
sources it describes and `drift.lock.json` records a digest of them. When
the digest moves, the chapter is *suspect*, not wrong: a human reads it,
decides, and re-baselines with `accept`.

The lock is therefore a record of what somebody confirmed. Baselining
everything to clear the output empties it of meaning, which is why `accept`
takes one chapter at a time and refuses an unknown id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

LOCK = "handbook/drift.lock.json"

#: Directories whose contents are build output, not source. Hashing them
#: would make the digest move on a `cargo build`, and a check that cries
#: wolf gets baselined away.
IGNORED_DIRS = {
    "__pycache__", ".git", "node_modules", "target", "dist", "build",
    ".pytest_cache", ".venv", ".mypy_cache", ".ruff_cache",
}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".so", ".lock"}

#: Distinguishes "the path is not there" from "the path is there and empty".
ABSENT = "\x00absent"


def _files(path: Path):
    if path.is_file():
        yield path
        return
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        if any(part in IGNORED_DIRS for part in child.parts):
            continue
        if child.suffix in IGNORED_SUFFIXES:
            continue
        yield child


def digest(root: Path, paths: list[str]) -> str:
    """A stable digest of every watched file's path *and* content.

    Paths go into the hash as well as bytes, so a rename registers even
    though nothing was edited.
    """
    root = Path(root)
    sha = hashlib.sha256()
    for rel in sorted(paths):
        target = root / rel
        if not target.exists():
            sha.update(f"{rel}{ABSENT}\n".encode())
            continue
        sha.update(f"{rel}\n".encode())
        for path in _files(target):
            sha.update(str(path.relative_to(root)).encode())
            sha.update(b"\x00")
            sha.update(hashlib.sha256(path.read_bytes()).digest())
    return sha.hexdigest()


def load_lock(root: Path) -> dict[str, str]:
    lock_file = Path(root) / LOCK
    if not lock_file.is_file():
        return {}
    return json.loads(lock_file.read_text(encoding="utf-8"))


def save_lock(root: Path, lock: dict[str, str]) -> None:
    lock_file = Path(root) / LOCK
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(lock, indent=2, sort_keys=True)
    lock_file.write_text(body + "\n", encoding="utf-8")


@dataclass(frozen=True)
class DriftReport:
    chapter: str
    #: One of: unwatched, unbaselined, drifted, current.
    state: str
    watches: list[str]


def compare(root: Path, chapters, lock: dict[str, str]) -> list[DriftReport]:
    report = []
    for chapter in chapters:
        if not chapter.watches:
            report.append(DriftReport(chapter.id, "unwatched", []))
            continue
        current = digest(root, chapter.watches)
        recorded = lock.get(chapter.id)
        if recorded is None:
            state = "unbaselined"
        elif recorded != current:
            state = "drifted"
        else:
            state = "current"
        report.append(DriftReport(chapter.id, state, list(chapter.watches)))
    return report


def baseline(root: Path, chapters) -> dict[str, str]:
    """Digest every watched chapter. Used to seed a fresh lock."""
    return {c.id: digest(root, c.watches) for c in chapters if c.watches}


def accept(root: Path, chapters, lock: dict[str, str], chapter_id: str) -> dict[str, str]:
    """Re-baseline exactly one chapter, by id."""
    for chapter in chapters:
        if chapter.id == chapter_id:
            updated = dict(lock)
            updated[chapter_id] = digest(root, chapter.watches)
            return updated
    raise KeyError(f"no chapter with id {chapter_id!r}")
