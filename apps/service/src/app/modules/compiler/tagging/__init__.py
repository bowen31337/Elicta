"""Validates and persists each compiled candidate's PRD FR-4.2 tag set and PRD FR-4.3 embedding."""

from __future__ import annotations

from app.modules.compiler.tagging.embed_candidates import (
    EmbedCandidatePhrasing,
    SaveCandidateEmbedding,
    compute_bank_embeddings,
    compute_candidate_embedding,
    persist_candidate_embeddings,
)
from app.modules.compiler.tagging.models import (
    CandidateEmbedding,
    CandidateTagging,
    CandidateTags,
    TaggedCandidate,
)
from app.modules.compiler.tagging.tag_candidates import (
    SaveTaggedCandidate,
    persist_candidate_tags,
    tag_candidates,
)

__all__ = [
    "CandidateEmbedding",
    "CandidateTagging",
    "CandidateTags",
    "EmbedCandidatePhrasing",
    "SaveCandidateEmbedding",
    "SaveTaggedCandidate",
    "TaggedCandidate",
    "compute_bank_embeddings",
    "compute_candidate_embedding",
    "persist_candidate_embeddings",
    "persist_candidate_tags",
    "tag_candidates",
]
