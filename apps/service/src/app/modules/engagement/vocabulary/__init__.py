"""Engagement vocabulary package: client product names, internal systems, and
acronyms feeding FR-2.3's keyterm prompting (PRD FR-3.6); also the
engagement's expected-language set derived from client context, constraining
ASR language detection (PRD FR-2.14).
"""

from __future__ import annotations

from .errors import EngagementNotFoundError
from .language import (
    ClientContext,
    ExpectedLanguageSet,
    SaveExpectedLanguages,
    derive_and_persist_expected_languages,
    derive_expected_languages,
)
from .router import AddVocabularyTerm, build_vocabulary_router
from .schemas import (
    VocabularyTermCreateRequest,
    VocabularyTermResponse,
    VocabularyTermType,
)

__all__ = [
    "AddVocabularyTerm",
    "ClientContext",
    "EngagementNotFoundError",
    "ExpectedLanguageSet",
    "SaveExpectedLanguages",
    "VocabularyTermCreateRequest",
    "VocabularyTermResponse",
    "VocabularyTermType",
    "build_vocabulary_router",
    "derive_and_persist_expected_languages",
    "derive_expected_languages",
]
