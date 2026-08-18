"""Tests for extracting text from a reference document's raw bytes (PRD FR-3.3)."""

from __future__ import annotations

from .extraction import extract_text


def test_extracts_utf8_text_verbatim():
    assert extract_text("Scope: rebuild the intake pipeline.".encode("utf-8")) == (
        "Scope: rebuild the intake pipeline."
    )


def test_extracts_non_ascii_utf8_text():
    text = "The client's São Paulo office leads procurement."
    assert extract_text(text.encode("utf-8")) == text


def test_empty_content_returns_empty_string():
    assert extract_text(b"") == ""


def test_undecodable_bytes_degrade_to_replacement_characters_without_raising():
    content = b"\xff\xfe\x00\x01not valid utf-8"

    result = extract_text(content)

    assert isinstance(result, str)
    assert "�" in result
