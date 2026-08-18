"""Debrief artifacts package: durable deliverables assembled from pipeline stage output.

Exposes no mounted router — `build_full_prd_router` needs real dependencies
injected first — so this package is consumed directly by whichever part of
the `debrief` module drives artifact generation once a session's pipeline
stages have completed, and by whoever wires the app factory to mount the
router it builds. `build_coverage_matrix` turns one `COMPLETE`
`SessionSectionClassification` (PRD FR-8.2, from `debrief/pipeline`) into the
requirements coverage matrix artifact itself: one entry per BMAD taxonomy
section, each `FILLED` entry grounded in a record-path citation (PRD
FR-2.7/FR-8.7). `require_prd_generation_coverage` then gates full PRD
generation on that coverage accumulated across an engagement's meetings (PRD
FR-8.10), and `build_full_prd_router` is the HTTP surface that turns a
failed gate into a 409.
"""

from __future__ import annotations

from app.modules.debrief.artifacts.matrix import CiteFilledSlot, SaveCoverageMatrix, build_coverage_matrix
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageGapSection,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    EngagementCoverageSummary,
    RequirementsCoverageMatrix,
)
from app.modules.debrief.artifacts.prd_gate import (
    DEFAULT_PRD_COVERAGE_THRESHOLD,
    PrdGenerationRefused,
    require_prd_generation_coverage,
    summarize_engagement_coverage,
)
from app.modules.debrief.artifacts.router import (
    GenerateFullPrd,
    GetEngagementCoverageMatrices,
    build_full_prd_router,
)

__all__ = [
    "DEFAULT_PRD_COVERAGE_THRESHOLD",
    "CiteFilledSlot",
    "CoverageCitation",
    "CoverageGapSection",
    "CoverageMatrixEntry",
    "CoverageMatrixStatus",
    "EngagementCoverageSummary",
    "GenerateFullPrd",
    "GetEngagementCoverageMatrices",
    "PrdGenerationRefused",
    "RequirementsCoverageMatrix",
    "SaveCoverageMatrix",
    "build_coverage_matrix",
    "build_full_prd_router",
    "require_prd_generation_coverage",
    "summarize_engagement_coverage",
]
