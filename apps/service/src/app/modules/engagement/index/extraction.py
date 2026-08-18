"""Extracts text content from a reference document's raw bytes (PRD FR-3.3).

No PDF/DOCX parsing dependency is available in this service yet (see
`pyproject.toml`), so `extract_text` only does real extraction for
text-decodable formats (`.txt`, `.md`, and similar) — the case FR-3.3's
retrieval indexing actually needs content from. Binary formats still decode
rather than raise: `errors="replace"` swaps undecodable bytes for U+FFFD so
the extract/chunk/index pipeline degrades gracefully into low-quality
chunks instead of failing the whole document, leaving real binary-format
extraction for whoever adds that dependency later.
"""

from __future__ import annotations


def extract_text(content: bytes) -> str:
    """Decodes a document's raw bytes into text for chunking (PRD FR-3.3)."""

    if not content:
        return ""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")
