"""Engagement vocabulary package: client product names, internal systems, and
acronyms feeding FR-2.3's keyterm prompting (PRD FR-3.6).
"""

from __future__ import annotations

from .errors import EngagementNotFoundError
from .router import AddVocabularyTerm, build_vocabulary_router
from .schemas import (
    VocabularyTermCreateRequest,
    VocabularyTermResponse,
    VocabularyTermType,
)

__all__ = [
    "AddVocabularyTerm",
    "EngagementNotFoundError",
    "VocabularyTermCreateRequest",
    "VocabularyTermResponse",
    "VocabularyTermType",
    "build_vocabulary_router",
]
