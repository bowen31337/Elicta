"""Engagement document indexing: extract, chunk, and index reference document
content for retrieval (PRD FR-3.3).

`extract_text` turns a document's raw upload bytes into text.  `chunk_text`
splits that text into retrieval-sized, whitespace-safe chunks. `index_document`
runs both, hands the resulting chunks to an injected `IndexChunks` callback,
and persists an `indexed_at` timestamp per document via an injected
`MarkDocumentIndexed` callback — the PRD FR-3.3 requirement this package
exists for.
"""

from __future__ import annotations

from .chunking import DEFAULT_CHUNK_SIZE, chunk_text
from .extraction import extract_text
from .models import DocumentChunk, DocumentIndexRecord
from .service import IndexChunks, MarkDocumentIndexed, index_document

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DocumentChunk",
    "DocumentIndexRecord",
    "IndexChunks",
    "MarkDocumentIndexed",
    "chunk_text",
    "extract_text",
    "index_document",
]
