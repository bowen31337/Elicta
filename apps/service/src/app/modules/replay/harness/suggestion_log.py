"""Parses the suggestion log the shared core emits on stdout.

The core writes one JSON object per line (NDJSON) — one line per surfaced
suggestion, in the order the core surfaced them. Parsing into
`SuggestionLogEntry` rather than comparing raw bytes is what lets
`comparison.py` name exactly which entry two platforms disagree on, instead
of just reporting that "the bytes differ".
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .errors import SuggestionLogError

_REQUIRED_FIELDS = ("span_id", "candidate_id", "stub", "priority")


@dataclass(frozen=True)
class SuggestionLogEntry:
    """One suggestion the shared core surfaced during a replay run.

    `span_id` ties the suggestion back to the trigger span that produced
    it, `candidate_id` back to the compiled question-bank row it came from
    (architecture section 3.6), `stub` is its glanceable form, and
    `priority` is the rank the core's scoring function assigned it.
    """

    span_id: str
    candidate_id: str
    stub: str
    priority: int


def parse_suggestion_log(data: bytes) -> list[SuggestionLogEntry]:
    """Parses NDJSON suggestion-log bytes into ordered `SuggestionLogEntry` rows.

    Raises `SuggestionLogError` on any line that isn't valid JSON or is
    missing a required field, rather than skipping it — a suggestion log
    with silently-dropped entries would compare as identical across
    platforms even when it isn't.
    """

    entries: list[SuggestionLogEntry] = []
    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuggestionLogError(f"line {line_number}: invalid JSON: {exc}") from exc

        missing = [field for field in _REQUIRED_FIELDS if field not in payload]
        if missing:
            raise SuggestionLogError(
                f"line {line_number}: missing field(s) {missing}"
            )

        entries.append(
            SuggestionLogEntry(
                span_id=payload["span_id"],
                candidate_id=payload["candidate_id"],
                stub=payload["stub"],
                priority=payload["priority"],
            )
        )

    return entries
