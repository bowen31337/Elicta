"""Request/response DTOs for the engagement vocabulary API (PRD FR-3.6)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VocabularyTermType(str, Enum):
    """The categories FR-3.6 asks the vocabulary list to distinguish."""

    PRODUCT_NAME = "product_name"
    INTERNAL_SYSTEM = "internal_system"
    ACRONYM = "acronym"


class VocabularyTermCreateRequest(BaseModel):
    term: str = Field(min_length=1)
    term_type: VocabularyTermType


class VocabularyTermResponse(BaseModel):
    term_id: str
    engagement_id: str
    term: str
    term_type: VocabularyTermType
