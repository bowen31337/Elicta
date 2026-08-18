"""Engagement document indexing: extract, chunk, and index reference document
content for retrieval (PRD FR-3.3).

`extract_text` turns a document's raw upload bytes into text.  `chunk_text`
splits that text into retrieval-sized, whitespace-safe chunks. `index_document`
runs both, hands the resulting chunks to an injected `IndexChunks` callback
for the retrieval index (slow-lane, raw text), and persists a compact
`ContextPackDigest` per document via an injected `PersistPackDigest`
callback — the "compile, don't dump" requirement FR-3.3's rationale asks
for, so the context pack that feeds the cached prompt prefix never
accumulates raw text.
"""

from __future__ import annotations

from .chunking import DEFAULT_CHUNK_SIZE, chunk_text
from .extraction import extract_text
from .models import ContextPackDigest, DocumentChunk
from .service import IndexChunks, PersistPackDigest, index_document

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "ContextPackDigest",
    "DocumentChunk",
    "IndexChunks",
    "PersistPackDigest",
    "chunk_text",
    "extract_text",
    "index_document",
]
