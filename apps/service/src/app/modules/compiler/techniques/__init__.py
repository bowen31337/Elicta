"""Compiling techniques that turn engagement source material into bank candidates (PRD FR-4.6, FR-4.7, FR-4.9)."""

from __future__ import annotations

from app.modules.compiler.techniques.authority_matching import (
    CandidateAuthorityMatch,
    compute_bank_authority_matches,
    compute_candidate_authority_match,
    persist_candidate_authority_matches,
)
from app.modules.compiler.techniques.hypothesis_verification import (
    VERIFICATION_TEMPLATE_SECTION,
    generate_verification_questions,
)
from app.modules.compiler.techniques.models import (
    CandidateAuthorityRequirement,
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
    "CandidateAuthorityMatch",
    "CandidateAuthorityRequirement",
    "CandidateShape",
    "EngagementStage",
    "HypothesisDocumentClaim",
    "ShapedCandidate",
    "StageSuppressionResult",
    "compute_bank_authority_matches",
    "compute_candidate_authority_match",
    "generate_verification_questions",
    "persist_candidate_authority_matches",
    "suppress_out_of_stage_candidates",
]
