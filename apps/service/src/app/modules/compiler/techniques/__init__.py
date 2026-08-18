"""Compiling techniques that turn engagement source material into bank candidates (PRD FR-4.9)."""

from __future__ import annotations

from app.modules.compiler.techniques.hypothesis_verification import (
    VERIFICATION_TEMPLATE_SECTION,
    generate_verification_questions,
)
from app.modules.compiler.techniques.models import HypothesisDocumentClaim

__all__ = [
    "VERIFICATION_TEMPLATE_SECTION",
    "HypothesisDocumentClaim",
    "generate_verification_questions",
]
