"""Tests for embedding and persisting each candidate's vector (PRD FR-4.3)."""

from __future__ import annotations

import asyncio

import pytest

from app.modules.compiler.tagging.embed_candidates import (
    compute_bank_embeddings,
    compute_candidate_embedding,
    persist_candidate_embeddings,
)
from app.modules.compiler.tagging.models import (
    CandidateEmbedding,
    CandidateTagging,
    CandidateTags,
)


def make_tagging(candidate_id: str, phrasing: str = "Can you clarify the scope?") -> CandidateTagging:
    return CandidateTagging(
        id=candidate_id,
        phrasing=phrasing,
        tags=CandidateTags(
            template_section="scope",
            trigger_types=["unquantified_adjective"],
            priority=1,
            requires=[],
        ),
    )


async def fake_embed(phrasing: str) -> bytes:
    return phrasing.encode("utf-8")


async def empty_embed(phrasing: str) -> bytes:
    return b""


def test_compute_candidate_embedding_wraps_the_embed_callables_vector():
    embedding = asyncio.run(
        compute_candidate_embedding("candidate-1", "Can you clarify the scope?", fake_embed)
    )

    assert embedding == CandidateEmbedding(
        candidate_id="candidate-1", embedding=b"Can you clarify the scope?"
    )


def test_compute_candidate_embedding_rejects_an_empty_vector():
    with pytest.raises(ValueError, match="candidate-1"):
        asyncio.run(compute_candidate_embedding("candidate-1", "Can you clarify the scope?", empty_embed))


def test_compute_bank_embeddings_embeds_every_candidates_phrasing_in_order():
    taggings = [
        make_tagging("candidate-1", phrasing="First question?"),
        make_tagging("candidate-2", phrasing="Second question?"),
    ]

    embeddings = asyncio.run(compute_bank_embeddings(taggings, fake_embed))

    assert embeddings == [
        CandidateEmbedding(candidate_id="candidate-1", embedding=b"First question?"),
        CandidateEmbedding(candidate_id="candidate-2", embedding=b"Second question?"),
    ]


def test_persist_candidate_embeddings_saves_every_computed_vector():
    saved: list[CandidateEmbedding] = []

    async def save(embedding: CandidateEmbedding) -> None:
        saved.append(embedding)

    taggings = [make_tagging("candidate-1"), make_tagging("candidate-2")]

    result = asyncio.run(persist_candidate_embeddings(taggings, fake_embed, save))

    assert saved == result
    assert [e.candidate_id for e in saved] == ["candidate-1", "candidate-2"]


def test_persist_candidate_embeddings_saves_nothing_when_a_vector_fails_to_compute():
    saved: list[CandidateEmbedding] = []

    async def save(embedding: CandidateEmbedding) -> None:
        saved.append(embedding)

    taggings = [make_tagging("candidate-1"), make_tagging("candidate-2")]

    with pytest.raises(ValueError):
        asyncio.run(persist_candidate_embeddings(taggings, empty_embed, save))

    assert saved == []
