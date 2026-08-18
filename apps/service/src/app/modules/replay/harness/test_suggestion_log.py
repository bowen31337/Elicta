from __future__ import annotations

import json

import pytest

from .errors import SuggestionLogError
from .suggestion_log import SuggestionLogEntry, parse_suggestion_log


def _line(**overrides: object) -> str:
    payload = {
        "span_id": "span-1",
        "candidate_id": "cand-1",
        "stub": "ask about renewal",
        "priority": 1,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parses_one_entry_per_line_in_order():
    data = "\n".join(
        [
            _line(span_id="span-1", candidate_id="cand-1", priority=1),
            _line(span_id="span-2", candidate_id="cand-2", priority=2),
        ]
    ).encode("utf-8")

    entries = parse_suggestion_log(data)

    assert entries == [
        SuggestionLogEntry(
            span_id="span-1", candidate_id="cand-1", stub="ask about renewal", priority=1
        ),
        SuggestionLogEntry(
            span_id="span-2", candidate_id="cand-2", stub="ask about renewal", priority=2
        ),
    ]


def test_blank_lines_are_skipped():
    data = (_line() + "\n\n" + _line(span_id="span-2")).encode("utf-8")

    entries = parse_suggestion_log(data)

    assert [entry.span_id for entry in entries] == ["span-1", "span-2"]


def test_empty_log_parses_to_no_entries():
    assert parse_suggestion_log(b"") == []


def test_invalid_json_raises_suggestion_log_error():
    with pytest.raises(SuggestionLogError, match="invalid JSON"):
        parse_suggestion_log(b"not json")


def test_missing_required_field_raises_suggestion_log_error():
    bad_line = json.dumps({"span_id": "span-1", "candidate_id": "cand-1"}).encode("utf-8")

    with pytest.raises(SuggestionLogError, match="priority"):
        parse_suggestion_log(bad_line)
