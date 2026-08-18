"""Validates and persists each compiled candidate's PRD FR-4.2 tag set."""

from __future__ import annotations

from app.modules.compiler.tagging.models import (
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
    "CandidateTagging",
    "CandidateTags",
    "SaveTaggedCandidate",
    "TaggedCandidate",
    "persist_candidate_tags",
    "tag_candidates",
]
