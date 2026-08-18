"""Domain types for reference document indexing (PRD FR-3.3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """One retrieval-sized slice of a reference document's extracted text (PRD FR-3.3).

    `order` is the chunk's position within the document, not a globally
    unique id — chunks are only ever addressed together with the
    `document_id` they came from.
    """

    document_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    text: str = Field(min_length=1)


class ContextPackDigest(BaseModel):
    """One document's compact contribution to the engagement's context pack:
    when it was indexed and how much content it carries -- never the
    extracted or chunked text itself (PRD FR-3.3).

    This is the "compile, don't dump" artifact FR-3.3's rationale asks for:
    a context pack built by accumulating raw document text inflates the
    cached prompt prefix and blows the latency budget (NFR-1), so what
    persists as the pack must stay a fixed-shape summary regardless of how
    large or numerous the source documents are. `chunk_count` and
    `char_count` size that summary without carrying any of the content that
    produced them; the actual text stays in the retrieval index (`DocumentChunk`,
    persisted via `IndexChunks`) for slow-lane use only. `chunk_count == 0`
    with a `char_count` of `0` tells a caller a document indexed with no
    extractable content apart from one that was never indexed at all (no
    `ContextPackDigest` yet), without a second lookup.
    """

    document_id: str = Field(min_length=1)
    indexed_at: datetime
    chunk_count: int = Field(ge=0)
    char_count: int = Field(ge=0)
