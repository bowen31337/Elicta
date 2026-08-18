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


class DocumentIndexRecord(BaseModel):
    """Result of indexing one reference document: when it happened and how
    much of it was indexed (PRD FR-3.3).

    `indexed_at` is the persisted timestamp FR-3.3 asks for. `chunk_count`
    is carried alongside it so a caller can tell a document indexed with no
    extractable content (`chunk_count == 0`) apart from one that was never
    indexed at all (no `DocumentIndexRecord` yet), without a second lookup.
    """

    document_id: str = Field(min_length=1)
    indexed_at: datetime
    chunk_count: int = Field(ge=0)
