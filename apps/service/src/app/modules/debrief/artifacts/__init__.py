"""Debrief artifacts package: durable deliverables assembled from pipeline stage output.

Exposes no router — this package is consumed by whichever part of the
`debrief` module drives artifact generation once a session's pipeline stages
have completed. `build_coverage_matrix` turns one `COMPLETE`
`SessionSectionClassification` (PRD FR-8.2, from `debrief/pipeline`) into the
requirements coverage matrix artifact itself: one entry per BMAD taxonomy
section, each `FILLED` entry grounded in a record-path citation (PRD
FR-2.7/FR-8.7).
"""

from __future__ import annotations

from app.modules.debrief.artifacts.matrix import CiteFilledSlot, SaveCoverageMatrix, build_coverage_matrix
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
)

__all__ = [
    "CiteFilledSlot",
    "CoverageCitation",
    "CoverageMatrixEntry",
    "CoverageMatrixStatus",
    "RequirementsCoverageMatrix",
    "SaveCoverageMatrix",
    "build_coverage_matrix",
]
