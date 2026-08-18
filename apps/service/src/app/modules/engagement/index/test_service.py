"""Tests for the extract/chunk/index pipeline (PRD FR-3.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import ContextPackDigest, DocumentChunk
from .service import index_document


def make_recorders():
    indexed_calls: list[tuple[str, list[DocumentChunk]]] = []
    digest_calls: list[tuple[str, ContextPackDigest]] = []

    async def index_chunks(document_id: str, chunks: list[DocumentChunk]) -> None:
        indexed_calls.append((document_id, chunks))

    async def persist_digest(document_id: str, digest: ContextPackDigest) -> None:
        digest_calls.append((document_id, digest))

    return index_chunks, persist_digest, indexed_calls, digest_calls


async def test_indexes_document_content_into_chunks():
    index_chunks, persist_digest, indexed_calls, _ = make_recorders()
    content = ("word " * 50).strip().encode("utf-8")

    await index_document(
        "doc-1", content, index_chunks, persist_digest, chunk_size=20
    )

    assert len(indexed_calls) == 1
    document_id, chunks = indexed_calls[0]
    assert document_id == "doc-1"
    assert len(chunks) > 1
    assert all(chunk.document_id == "doc-1" for chunk in chunks)
    assert [chunk.order for chunk in chunks] == list(range(len(chunks)))


async def test_persists_indexed_at_timestamp_per_document():
    index_chunks, persist_digest, _, digest_calls = make_recorders()
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    digest = await index_document(
        "doc-1",
        b"some reference content",
        index_chunks,
        persist_digest,
        indexed_at=fixed_time,
    )

    assert [document_id for document_id, _ in digest_calls] == ["doc-1"]
    assert digest_calls[0][1] == digest
    assert digest.document_id == "doc-1"
    assert digest.indexed_at == fixed_time


async def test_defaults_indexed_at_to_now_when_not_supplied():
    index_chunks, persist_digest, _, digest_calls = make_recorders()
    before = datetime.now(timezone.utc)

    digest = await index_document(
        "doc-1", b"some content", index_chunks, persist_digest
    )

    after = datetime.now(timezone.utc)
    assert before <= digest.indexed_at <= after
    assert [document_id for document_id, _ in digest_calls] == ["doc-1"]
    assert digest_calls[0][1].indexed_at == digest.indexed_at


async def test_empty_document_still_gets_indexed_with_zero_chunks():
    index_chunks, persist_digest, indexed_calls, digest_calls = make_recorders()

    digest = await index_document("doc-1", b"", index_chunks, persist_digest)

    assert indexed_calls == [("doc-1", [])]
    assert digest.chunk_count == 0
    assert digest.char_count == 0
    assert len(digest_calls) == 1


async def test_chunk_count_matches_number_of_chunks_produced():
    index_chunks, persist_digest, _, _ = make_recorders()
    content = ("word " * 50).strip().encode("utf-8")

    digest = await index_document(
        "doc-1", content, index_chunks, persist_digest, chunk_size=20
    )

    assert digest.chunk_count > 1


async def test_char_count_sums_chunked_text_length_not_raw_bytes():
    index_chunks, persist_digest, indexed_calls, _ = make_recorders()
    content = ("word " * 50).strip().encode("utf-8")

    digest = await index_document(
        "doc-1", content, index_chunks, persist_digest, chunk_size=20
    )

    _, chunks = indexed_calls[0]
    assert digest.char_count == sum(len(chunk.text) for chunk in chunks)


async def test_digest_never_carries_extracted_or_chunked_text():
    index_chunks, persist_digest, _, _ = make_recorders()

    await index_document(
        "doc-1", b"some reference content", index_chunks, persist_digest
    )

    assert set(ContextPackDigest.model_fields) == {
        "document_id",
        "indexed_at",
        "chunk_count",
        "char_count",
    }
