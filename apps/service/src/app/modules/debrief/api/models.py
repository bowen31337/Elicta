"""Request/response DTOs for the debrief artifacts API (PRD FR-8.1 through FR-8.7).

`ArtifactSummary` mirrors one row of the `artifacts` table (`session_id`,
`artifact_type`, `artifact_language`, `body`, `generated_at`) but carries
only `artifact_type` and `generated_at` — a caller listing what a meeting has
produced needs to know which of the six PRD FR-8.1-8.6 kinds exist and when
each was generated, not the full rendered `body` of every one, which the
per-artifact routes in `debrief/artifacts` already expose on their own routes.

`ArtifactDetail` mirrors the same `artifacts` row in full, by its own `id`
rather than by session and type: every field the summary omits (`id`,
`session_id`, `artifact_language`, `body`) plus the two the summary already
carries. `body` is typed as a plain `dict` rather than one of the six PRD
FR-8.1-8.6 artifact shapes because this package does not own the `artifacts`
table (PRD FR-8.7 citation expansion happens where that row is assembled,
out of this footprint) — it just plumbs the already-expanded JSONB body
through, the same "no transformation, just an injected lookup" contract
`ArtifactSummary`'s router uses.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

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


class ArtifactDetail(BaseModel):
    """One full `artifacts` table row, looked up by its own `id` (PRD FR-8.1 through FR-8.7).

    `body` carries the artifact's full rendered content with every citation
    it references already expanded into citation detail (utterance_id,
    timestamps, speaker, quoted/translated text) rather than left as a bare
    utterance_id — the same `ArtifactCitation`/`CitationRow` shape every
    other debrief artifact route already returns its citations in.
    """

    id: str
    session_id: str
    artifact_type: ArtifactType
    artifact_language: str
    body: dict[str, Any]
    generated_at: datetime
