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

`MeetingAttendee`, `MeetingCoverageSummary`, and `MeetingDetail` back the
single-meeting-by-id route (GET /api/meetings/{meeting_id}). `MeetingDetail`
aggregates across the `meetings`, `attendees`, and coverage-matrix/
nudge-disposition state, none of which this package owns, so it is filled in
by a single injected lookup rather than three separate table reads --
mirroring `ArtifactDetail`'s "no transformation, just an injected lookup"
contract. `MeetingAttendee` is a local mirror of `engagement/meetings`'s
persisted `Attendee` row (that package's record type does not live here) and
`MeetingCoverageSummary` condenses `debrief/artifacts`'s
`RequirementsCoverageMatrix` down to the counts a meeting-detail caller
needs at a glance, without the full per-section entry list.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    """Which of the six PRD FR-8.1-8.6 durable artifact kinds a row holds."""

    TRANSCRIPT = "transcript"
    COVERAGE_MATRIX = "coverage_matrix"
    OPEN_QUESTIONS = "open_questions"
    DECISION_LOG = "decision_log"
    PROJECT_BRIEF = "project_brief"
    FOLLOW_UP_EMAIL = "follow_up_email"


class ArtifactSummary(BaseModel):
    """One artifact a meeting has produced, listed by id, kind and generation time.

    `artifact_id` is what makes the list actionable: `ArtifactDetail` is
    addressed by its own id, and this list is the only place a caller can
    learn one. Without it the detail route was reachable only by guessing,
    which is to say not at all.
    """

    artifact_id: str
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


class MeetingAttendee(BaseModel):
    """One attendee on the meeting being read back (PRD FR-3.9, FR-3.10).

    Mirrors `engagement/meetings`'s persisted `Attendee` row rather than
    importing it, since that package's record type does not live in this
    package (`app/modules/debrief/api`) -- the same cross-module boundary
    `EngagementContext` draws in `engagement/meetings/models.py`.
    """

    id: str
    display_name: str | None = None
    role: str | None = None
    business_function: str | None = None
    decision_authority: str | None = None
    domain_expertise: list[str] = Field(default_factory=list)


class MeetingCoverageSummary(BaseModel):
    """A condensed readout of one meeting's requirements coverage matrix (PRD FR-8.2).

    Carries only the counts a meeting-detail caller needs to gauge progress
    at a glance -- how many BMAD taxonomy sections this meeting has filled
    versus how many exist -- rather than the full per-section
    `CoverageMatrixEntry` list `debrief/artifacts` already exposes on its own
    routes. `is_fully_covered` mirrors `RequirementsCoverageMatrix`'s own
    field of the same name.
    """

    filled_sections: int = Field(ge=0)
    total_sections: int = Field(ge=0)
    is_fully_covered: bool


class MeetingDetail(BaseModel):
    """A single meeting read back with its attendees, coverage summary, and nudge count.

    Aggregates across the `meetings` and `attendees` tables and the
    coverage-matrix/nudge-disposition state, none of which this package
    owns, so it is assembled by a single injected lookup rather than three
    separate reads -- the same "no transformation, just an injected lookup"
    contract `ArtifactDetail`'s router uses. `coverage_summary` is `None`
    until the meeting's debrief pipeline has run a section classification;
    `nudge_count` is the number of live-mode nudges that fired during the
    meeting's capture (PRD FR-7.4), `0` for a meeting with no live-mode
    capture yet.
    """

    meeting_id: str
    engagement_id: str
    state: str
    capture_mode: str
    scheduled_at: datetime | None = None
    attendees: list[MeetingAttendee]
    coverage_summary: MeetingCoverageSummary | None = None
    nudge_count: int = Field(ge=0)
