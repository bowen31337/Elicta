"""Compiling techniques that turn engagement source material into bank candidates (PRD FR-4.6, FR-4.9)."""

from __future__ import annotations

from app.modules.compiler.techniques.hypothesis_verification import (
    VERIFICATION_TEMPLATE_SECTION,
    generate_verification_questions,
)
from app.modules.compiler.techniques.models import (
    CandidateShape,
    EngagementStage,
    HypothesisDocumentClaim,
    ShapedCandidate,
)
from app.modules.compiler.techniques.stage_suppression import (
    StageSuppressionResult,
    suppress_out_of_stage_candidates,
)

__all__ = [
    "VERIFICATION_TEMPLATE_SECTION",
    "CandidateShape",
    "EngagementStage",
    "HypothesisDocumentClaim",
    "ShapedCandidate",
    "StageSuppressionResult",
    "generate_verification_questions",
    "suppress_out_of_stage_candidates",
]
