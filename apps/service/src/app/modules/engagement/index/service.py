"""Extracts, chunks, and indexes a reference document's content for retrieval (PRD FR-3.3).

`index_document` takes the chunk store and the `indexed_at` persistence as
injected `index_chunks`/`mark_indexed` callables rather than importing the
engagement/document persistence layer directly, mirroring every other
service in this codebase (`state/reference_claims.py`,
`vocabulary/language.py`): no durable store for indexed chunks or
`indexed_at` lives in this package. Whoever wires the app factory (out of
this feature's footprint) supplies the real, persistence-backed
implementations — including whatever retrieval backend actually serves
`index_chunks`' output — and calls `index_document` once a reference
document's content is available (upload, PRD FR-3.2, or link attachment).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .chunking import DEFAULT_CHUNK_SIZE, chunk_text
from .extraction import extract_text
from .models import DocumentChunk, DocumentIndexRecord

IndexChunks = Callable[[str, list[DocumentChunk]], Awaitable[None]]
MarkDocumentIndexed = Callable[[str, datetime], Awaitable[None]]


async def index_document(
    document_id: str,
    content: bytes,
    index_chunks: IndexChunks,
    mark_indexed: MarkDocumentIndexed,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    indexed_at: datetime | None = None,
) -> DocumentIndexRecord:
    """Runs the extract/chunk/index pipeline for one document (PRD FR-3.3).

    `index_chunks` is always called, even with an empty list for a document
    with no extractable content — an empty document is still a document
    that finished indexing, not one the pipeline skipped — so `mark_indexed`
    always follows it and every document ends up with an `indexed_at`
    timestamp once this returns.
    """

    text = extract_text(content)
    chunks = [
        DocumentChunk(document_id=document_id, order=order, text=chunk)
        for order, chunk in enumerate(chunk_text(text, chunk_size=chunk_size))
    ]

    await index_chunks(document_id, chunks)

    resolved_indexed_at = indexed_at or datetime.now(timezone.utc)
    await mark_indexed(document_id, resolved_indexed_at)

    return DocumentIndexRecord(
        document_id=document_id,
        indexed_at=resolved_indexed_at,
        chunk_count=len(chunks),
    )
