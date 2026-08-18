"""Request/response DTOs for the per-meeting artifact list API (PRD FR-8.1 through FR-8.6).

`ArtifactSummary` mirrors one row of the `artifacts` table (`session_id`,
`artifact_type`, `artifact_language`, `body`, `generated_at`) but carries
only `artifact_type` and `generated_at` — a caller listing what a meeting has
produced needs to know which of the six PRD FR-8.1-8.6 kinds exist and when
each was generated, not the full rendered `body` of every one, which the
per-artifact routes in `debrief/artifacts` already expose on their own routes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ArtifactType(str, Enum):
    """Which of the six PRD FR-8.1-8.6 durable artifact kinds a row holds."""

    TRANSCRIPT = "transcript"
    COVERAGE_MATRIX = "coverage_matrix"
    OPEN_QUESTIONS = "open_questions"
    DECISION_LOG = "decision_log"
    PROJECT_BRIEF = "project_brief"
    FOLLOW_UP_EMAIL = "follow_up_email"


class ArtifactSummary(BaseModel):
    """One artifact a meeting has produced, listed by kind and generation time."""

    artifact_type: ArtifactType
    generated_at: datetime
