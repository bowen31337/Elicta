"""Tests for splitting extracted document text into retrieval chunks (PRD FR-3.3)."""

from __future__ import annotations

import pytest

from .chunking import chunk_text


def test_short_text_fits_in_a_single_chunk():
    assert chunk_text("one two three", chunk_size=100) == ["one two three"]


def test_empty_text_returns_no_chunks():
    assert chunk_text("", chunk_size=100) == []


def test_whitespace_only_text_returns_no_chunks():
    assert chunk_text("   \n\t  ", chunk_size=100) == []


def test_splits_on_word_boundaries_once_chunk_size_is_exceeded():
    text = "aaaa bbbb cccc dddd"

    chunks = chunk_text(text, chunk_size=10)

    assert chunks == ["aaaa bbbb", "cccc dddd"]


def test_every_chunk_is_at_most_chunk_size_except_a_lone_oversized_word():
    text = "one two three four five six seven eight nine ten"

    chunks = chunk_text(text, chunk_size=12)

    assert all(len(chunk) <= 12 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_a_single_word_longer_than_chunk_size_is_kept_whole():
    text = "supercalifragilisticexpialidocious"

    chunks = chunk_text(text, chunk_size=5)

    assert chunks == [text]


def test_reassembling_chunks_preserves_word_order_and_content():
    text = " ".join(f"word{i}" for i in range(50))

    chunks = chunk_text(text, chunk_size=20)

    assert " ".join(chunks).split() == text.split()


def test_non_positive_chunk_size_raises_value_error():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=0)
