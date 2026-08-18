"""Verifies suggestion logs are identical across platforms (PRD NFR-3.8).

`assert_identical_suggestion_logs` is the check that turns NFR-3.8 from an
assumption into a demonstration: hand it one suggestion log per platform a
run was replayed on, and it either passes silently or raises
`SuggestionLogMismatchError` naming exactly where the first divergence is.
"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import SuggestionLogMismatchError
from .suggestion_log import parse_suggestion_log


def assert_identical_suggestion_logs(logs_by_platform: Mapping[str, bytes]) -> None:
    """Raises `SuggestionLogMismatchError` unless every platform's log is
    identical to the first, once parsed.

    Comparing parsed entries rather than raw bytes means incidental
    differences (trailing blank lines, key order within a JSON object)
    don't get mistaken for the real divergence NFR-3.8 cares about: the
    core surfacing different, differently-ordered, or differently-ranked
    suggestions on one platform than another.
    """

    platforms = list(logs_by_platform)
    if len(platforms) < 2:
        return

    baseline_platform = platforms[0]
    baseline = parse_suggestion_log(logs_by_platform[baseline_platform])

    for platform in platforms[1:]:
        entries = parse_suggestion_log(logs_by_platform[platform])
        if entries == baseline:
            continue

        index = _first_divergent_index(baseline, entries)
        raise SuggestionLogMismatchError(
            f"suggestion log for {platform!r} diverges from {baseline_platform!r} "
            f"at entry {index}: {_entry_at(baseline, index)!r} != "
            f"{_entry_at(entries, index)!r}"
        )


def _first_divergent_index(baseline: list, other: list) -> int:
    for index, (left, right) in enumerate(zip(baseline, other)):
        if left != right:
            return index
    return min(len(baseline), len(other))


def _entry_at(entries: list, index: int) -> object | None:
    return entries[index] if index < len(entries) else None
