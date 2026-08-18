"""Embeds each compiled candidate's phrasing and persists the vector on its row (PRD FR-4.3).

FR-4.3 asks the compiler to "embed candidates for sub-300ms retrieval at
runtime," and architecture §3.6 makes that concrete: `candidate.embedding` is
a `BLOB NOT NULL` column -- a live meeting ranks candidates against a local
index built from this column, never by re-embedding on the hot path, so a
row missing a vector is a row that can never be retrieved. This module is
what turns a tagged candidate's `phrasing` into that persisted vector.

It reuses `.models.CandidateTagging` as its input rather than inventing a
parallel `id`-plus-`phrasing` shape: that model already is "the local input
shape this module accepts ... an untyped `id` plus [what] a candidate-
producing technique proposes" (`tag_candidates.py`), and embedding needs
nothing from it beyond exactly those two fields.

`EmbedCandidatePhrasing` takes the embedding call itself as an injected
callable rather than importing a concrete embedding client, mirroring
`agent/bmad_analyst.py`'s `RunBmadAnalystPass`: no embedding model client
exists yet in this codebase, and this module stays usable regardless of
which one is eventually wired in. `persist_candidate_embeddings` takes the
save step the same injected way, mirroring `tag_candidates.py`'s
`persist_candidate_tags` and `techniques/authority_matching.py`'s
`persist_candidate_authority_matches`: no durable store for the `candidate`
table exists yet either, and each of these sibling passes persists only the
one column it computes, keyed by candidate id, rather than a full row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .models import CandidateEmbedding, CandidateTagging

EmbedCandidatePhrasing = Callable[[str], Awaitable[bytes]]
SaveCandidateEmbedding = Callable[[CandidateEmbedding], Awaitable[None]]


async def compute_candidate_embedding(
    candidate_id: str, phrasing: str, embed: EmbedCandidatePhrasing
) -> CandidateEmbedding:
    """Embed `phrasing` via `embed` and return the resulting `CandidateEmbedding` for `candidate_id`.

    Raises `ValueError` naming `candidate_id` if `embed` returns an empty
    vector: an empty `bytes` would still satisfy `candidate.embedding`'s
    `NOT NULL` constraint while leaving the row unretrievable, so this is
    caught here rather than persisted as a row that looks embedded but isn't.
    """

    vector = await embed(phrasing)
    if not vector:
        raise ValueError(
            f"candidate {candidate_id!r} embedded to an empty vector"
        )
    return CandidateEmbedding(candidate_id=candidate_id, embedding=vector)


async def compute_bank_embeddings(
    taggings: list[CandidateTagging], embed: EmbedCandidatePhrasing
) -> list[CandidateEmbedding]:
    """Embed every candidate's `phrasing` in `taggings`, preserving their order."""

    return [
        await compute_candidate_embedding(tagging.id, tagging.phrasing, embed)
        for tagging in taggings
    ]


async def persist_candidate_embeddings(
    taggings: list[CandidateTagging],
    embed: EmbedCandidatePhrasing,
    save: SaveCandidateEmbedding,
) -> list[CandidateEmbedding]:
    """Compute every candidate's embedding via `compute_bank_embeddings`, then persist each one through `save`.

    Mirrors `tag_candidates.py`'s `persist_candidate_tags`: every vector is
    computed before any row is saved, and each is persisted in the order
    `taggings` was given.
    """

    embeddings = await compute_bank_embeddings(taggings, embed)
    for embedding in embeddings:
        await save(embedding)
    return embeddings
