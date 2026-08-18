"""Tests for the extract/chunk/index pipeline (PRD FR-3.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import DocumentChunk
from .service import index_document


def make_recorders():
    indexed_calls: list[tuple[str, list[DocumentChunk]]] = []
    marked_calls: list[tuple[str, datetime]] = []

    async def index_chunks(document_id: str, chunks: list[DocumentChunk]) -> None:
        indexed_calls.append((document_id, chunks))

    async def mark_indexed(document_id: str, indexed_at: datetime) -> None:
        marked_calls.append((document_id, indexed_at))

    return index_chunks, mark_indexed, indexed_calls, marked_calls


async def test_indexes_document_content_into_chunks():
    index_chunks, mark_indexed, indexed_calls, _ = make_recorders()
    content = ("word " * 50).strip().encode("utf-8")

    await index_document(
        "doc-1", content, index_chunks, mark_indexed, chunk_size=20
    )

    assert len(indexed_calls) == 1
    document_id, chunks = indexed_calls[0]
    assert document_id == "doc-1"
    assert len(chunks) > 1
    assert all(chunk.document_id == "doc-1" for chunk in chunks)
    assert [chunk.order for chunk in chunks] == list(range(len(chunks)))


async def test_persists_indexed_at_timestamp_per_document():
    index_chunks, mark_indexed, _, marked_calls = make_recorders()
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    record = await index_document(
        "doc-1",
        b"some reference content",
        index_chunks,
        mark_indexed,
        indexed_at=fixed_time,
    )

    assert marked_calls == [("doc-1", fixed_time)]
    assert record.document_id == "doc-1"
    assert record.indexed_at == fixed_time


async def test_defaults_indexed_at_to_now_when_not_supplied():
    index_chunks, mark_indexed, _, marked_calls = make_recorders()
    before = datetime.now(timezone.utc)

    record = await index_document(
        "doc-1", b"some content", index_chunks, mark_indexed
    )

    after = datetime.now(timezone.utc)
    assert before <= record.indexed_at <= after
    assert marked_calls == [("doc-1", record.indexed_at)]


async def test_empty_document_still_gets_indexed_with_zero_chunks():
    index_chunks, mark_indexed, indexed_calls, marked_calls = make_recorders()

    record = await index_document("doc-1", b"", index_chunks, mark_indexed)

    assert indexed_calls == [("doc-1", [])]
    assert record.chunk_count == 0
    assert len(marked_calls) == 1


async def test_chunk_count_matches_number_of_chunks_produced():
    index_chunks, mark_indexed, _, _ = make_recorders()
    content = ("word " * 50).strip().encode("utf-8")

    record = await index_document(
        "doc-1", content, index_chunks, mark_indexed, chunk_size=20
    )

    assert record.chunk_count > 1
