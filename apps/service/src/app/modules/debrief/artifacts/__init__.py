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
failed gate into a 409. `merge_requirements_state_forward` is the last
pipeline stage: it folds one meeting's coverage matrix and BMAD artifacts
into the engagement's standing `RequirementsState`, carrying confirmed
requirements, contradictions, and decisions forward into the next meeting
(PRD FR-8.9). `build_full_prd_router` also optionally exposes that standing
state via `GET /{engagement_id}/requirements-state`, so a UI can render each
decision's `provenance` — `STATED` or `INFERRED` (PRD FR-8.8) — well before
the full PRD is reachable. `build_project_brief_router` exposes the draft
project brief the same way, one meeting at a time: a plain
`GET /api/sessions/{session_id}/project-brief` reading the session's own
`SessionBmadAnalystChain` (built in `debrief/pipeline`), with no coverage
gate at all since a single meeting's draft brief needs no cross-meeting
evidence (PRD FR-8.5).
"""

from __future__ import annotations

from app.modules.debrief.artifacts.matrix import CiteFilledSlot, SaveCoverageMatrix, build_coverage_matrix
from app.modules.debrief.artifacts.models import (
    ConfirmedRequirement,
    CoverageCitation,
    CoverageGapSection,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    EngagementCoverageSummary,
    RequirementsCoverageMatrix,
    RequirementsContradiction,
    RequirementsState,
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
    GetRequirementsState,
    GetSessionBmadAnalystChain,
    build_full_prd_router,
    build_project_brief_router,
)
from app.modules.debrief.artifacts.state import SaveRequirementsState, merge_requirements_state_forward

__all__ = [
    "DEFAULT_PRD_COVERAGE_THRESHOLD",
    "CiteFilledSlot",
    "ConfirmedRequirement",
    "CoverageCitation",
    "CoverageGapSection",
    "CoverageMatrixEntry",
    "CoverageMatrixStatus",
    "EngagementCoverageSummary",
    "GenerateFullPrd",
    "GetEngagementCoverageMatrices",
    "GetRequirementsState",
    "GetSessionBmadAnalystChain",
    "PrdGenerationRefused",
    "RequirementsContradiction",
    "RequirementsCoverageMatrix",
    "RequirementsState",
    "SaveCoverageMatrix",
    "SaveRequirementsState",
    "build_coverage_matrix",
    "build_full_prd_router",
    "build_project_brief_router",
    "merge_requirements_state_forward",
    "require_prd_generation_coverage",
    "summarize_engagement_coverage",
]
