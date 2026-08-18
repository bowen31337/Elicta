"""Compiling techniques that turn engagement source material into bank candidates (PRD FR-4.6, FR-4.7, FR-4.9)."""

from __future__ import annotations

from app.modules.compiler.techniques.authority_matching import (
    CandidateAuthorityMatch,
    compute_bank_authority_matches,
    compute_candidate_authority_match,
    persist_candidate_authority_matches,
)
from app.modules.compiler.techniques.elicitation_technique_set import (
    DEFAULT_SKILL_DIR,
    load_elicitation_technique_set,
    verify_candidate_techniques,
)
from app.modules.compiler.techniques.hypothesis_verification import (
    VERIFICATION_TEMPLATE_SECTION,
    generate_verification_questions,
)
from app.modules.compiler.techniques.models import (
    CandidateAuthorityRequirement,
    CandidateShape,
    ElicitationTechnique,
    ElicitationTechniqueSet,
    EngagementStage,
    HypothesisDocumentClaim,
    ShapedCandidate,
    TechniqueDrawnCandidate,
    TechniqueVerificationResult,
    VerifiedTechniqueCandidate,
)
from app.modules.compiler.techniques.stage_suppression import (
    StageSuppressionResult,
    suppress_out_of_stage_candidates,
)

__all__ = [
    "DEFAULT_SKILL_DIR",
    "VERIFICATION_TEMPLATE_SECTION",
    "CandidateAuthorityMatch",
    "CandidateAuthorityRequirement",
    "CandidateShape",
    "ElicitationTechnique",
    "ElicitationTechniqueSet",
    "EngagementStage",
    "HypothesisDocumentClaim",
    "ShapedCandidate",
    "StageSuppressionResult",
    "TechniqueDrawnCandidate",
    "TechniqueVerificationResult",
    "VerifiedTechniqueCandidate",
    "compute_bank_authority_matches",
    "compute_candidate_authority_match",
    "generate_verification_questions",
    "load_elicitation_technique_set",
    "persist_candidate_authority_matches",
    "suppress_out_of_stage_candidates",
    "verify_candidate_techniques",
]
