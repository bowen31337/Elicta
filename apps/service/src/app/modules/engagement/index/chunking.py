"""Splits extracted document text into retrieval-sized chunks (PRD FR-3.3).

Chunks on whitespace rather than a fixed byte offset, so a chunk boundary
never lands mid-word — a split word would be useless as a standalone
retrieval unit. A single word longer than `chunk_size` is still kept whole
in its own oversized chunk instead of being cut, for the same reason.
"""

from __future__ import annotations

DEFAULT_CHUNK_SIZE = 1000


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    """Greedily packs whitespace-delimited words into chunks of at most
    `chunk_size` characters (PRD FR-3.3).

    Returns an empty list for text with no words (empty or whitespace-only
    content) rather than a single empty chunk, since there is nothing there
    to index.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        added_len = len(word) if not current else len(word) + 1
        if current and current_len + added_len > chunk_size:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += added_len
    if current:
        chunks.append(" ".join(current))

    return chunks
