"""Extracts, chunks, and indexes a reference document's content for retrieval (PRD FR-3.3).

`index_document` takes the chunk store and the context-pack digest
persistence as injected `index_chunks`/`persist_digest` callables rather
than importing the engagement/document persistence layer directly,
mirroring every other service in this codebase (`state/reference_claims.py`,
`vocabulary/language.py`): no durable store for indexed chunks or context
pack digests lives in this package. Whoever wires the app factory (out of
this feature's footprint) supplies the real, persistence-backed
implementations — including whatever retrieval backend actually serves
`index_chunks`' output — and calls `index_document` once a reference
document's content is available (upload, PRD FR-3.2, or link attachment).

`index_chunks` and `persist_digest` are deliberately two separate seams
rather than one: FR-3.3's rationale is "compile, don't dump" — raw chunk
text stays in the retrieval index for slow-lane use only, while the context
pack that feeds the cached prompt prefix persists as the compact
`ContextPackDigest` alone, so a caller can never accidentally reconstruct
the pack out of accumulated raw text by wiring both callbacks to the same
store.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .chunking import DEFAULT_CHUNK_SIZE, chunk_text
from .extraction import extract_text
from .models import ContextPackDigest, DocumentChunk

IndexChunks = Callable[[str, list[DocumentChunk]], Awaitable[None]]
PersistPackDigest = Callable[[str, ContextPackDigest], Awaitable[None]]


async def index_document(
    document_id: str,
    content: bytes,
    index_chunks: IndexChunks,
    persist_digest: PersistPackDigest,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    indexed_at: datetime | None = None,
) -> ContextPackDigest:
    """Runs the extract/chunk/index pipeline for one document (PRD FR-3.3).

    `index_chunks` is always called, even with an empty list for a document
    with no extractable content — an empty document is still a document
    that finished indexing, not one the pipeline skipped — so `persist_digest`
    always follows it and every document ends up with a `ContextPackDigest`
    once this returns. The digest's `char_count` is measured off the chunked
    text (post whitespace-normalization), not the raw extracted text, since
    that is the actual size the retrieval index carries for this document.
    """

    text = extract_text(content)
    chunk_texts = chunk_text(text, chunk_size=chunk_size)
    chunks = [
        DocumentChunk(document_id=document_id, order=order, text=chunk)
        for order, chunk in enumerate(chunk_texts)
    ]

    await index_chunks(document_id, chunks)

    resolved_indexed_at = indexed_at or datetime.now(UTC)
    digest = ContextPackDigest(
        document_id=document_id,
        indexed_at=resolved_indexed_at,
        chunk_count=len(chunks),
        char_count=sum(len(chunk) for chunk in chunk_texts),
    )
    await persist_digest(document_id, digest)

    return digest
