from __future__ import annotations

import json

import pytest

from .comparison import assert_identical_suggestion_logs
from .errors import SuggestionLogMismatchError


def _entry(**overrides: object) -> dict:
    payload = {
        "span_id": "span-1",
        "candidate_id": "cand-1",
        "stub": "ask about renewal",
        "priority": 1,
    }
    payload.update(overrides)
    return payload


def _log(*entries: dict) -> bytes:
    return "\n".join(json.dumps(entry) for entry in entries).encode("utf-8")


def test_identical_logs_across_platforms_pass():
    log = _log(_entry())

    assert_identical_suggestion_logs({"macos": log, "windows": log, "linux": log})


def test_a_single_platform_needs_no_comparison():
    assert_identical_suggestion_logs({"macos": _log(_entry())})


def test_no_platforms_needs_no_comparison():
    assert_identical_suggestion_logs({})


def test_a_divergent_entry_raises_naming_both_platforms():
    macos_log = _log(_entry(priority=1))
    windows_log = _log(_entry(priority=2))

    with pytest.raises(SuggestionLogMismatchError, match="'windows'.*'macos'"):
        assert_identical_suggestion_logs({"macos": macos_log, "windows": windows_log})


def test_error_names_the_first_divergent_entry_index():
    macos_log = _log(_entry(span_id="span-1"), _entry(span_id="span-2"))
    windows_log = _log(_entry(span_id="span-1"), _entry(span_id="span-DIFFERENT"))

    with pytest.raises(SuggestionLogMismatchError, match="entry 1"):
        assert_identical_suggestion_logs({"macos": macos_log, "windows": windows_log})


def test_an_extra_trailing_entry_is_still_a_mismatch():
    macos_log = _log(_entry(span_id="span-1"))
    windows_log = _log(_entry(span_id="span-1"), _entry(span_id="span-2"))

    with pytest.raises(SuggestionLogMismatchError, match="entry 1"):
        assert_identical_suggestion_logs({"macos": macos_log, "windows": windows_log})


def test_incidental_trailing_blank_lines_do_not_count_as_a_mismatch():
    macos_log = _log(_entry())
    windows_log = macos_log + b"\n\n"

    assert_identical_suggestion_logs({"macos": macos_log, "windows": windows_log})
