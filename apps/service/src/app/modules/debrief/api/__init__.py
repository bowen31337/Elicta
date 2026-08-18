"""Debrief API package: the per-meeting artifact list, a single artifact by id, and a single meeting by id (PRD FR-8.1 through FR-8.7).

Exposes no mounted router — `build_meeting_artifacts_router`,
`build_artifact_detail_router`, and `build_meeting_detail_router` each need a
real table read injected first — so this package is consumed directly by
whoever wires the app factory. `GET /api/meetings/{meeting_id}/artifacts`
always returns 200 with whatever `ArtifactSummary` list the lookup returns,
including an empty list for a meeting with no artifacts generated yet: a
meeting's artifact list has no "not found" state the way a single artifact
route does, it is simply empty until the debrief pipeline produces
something. `GET /api/artifacts/{artifact_id}` is that single artifact
route: it 404s when the id names no persisted row, and otherwise returns 200
with the full `ArtifactDetail`, its `body` already carrying every citation
it references expanded rather than left as a bare utterance_id. `GET
/api/meetings/{meeting_id}` similarly 404s when the id names no persisted
meeting, and otherwise returns 200 with the meeting's attendees, a condensed
coverage summary, and its live-mode nudge count.
"""

from __future__ import annotations

from app.modules.debrief.api.models import (
    ArtifactDetail,
    ArtifactSummary,
    ArtifactType,
    MeetingAttendee,
    MeetingCoverageSummary,
    MeetingDetail,
)
from app.modules.debrief.api.router import (
    GetArtifactById,
    GetMeetingArtifacts,
    GetMeetingDetail,
    build_artifact_detail_router,
    build_meeting_artifacts_router,
    build_meeting_detail_router,
)

__all__ = [
    "ArtifactDetail",
    "ArtifactSummary",
    "ArtifactType",
    "GetArtifactById",
    "GetMeetingArtifacts",
    "GetMeetingDetail",
    "MeetingAttendee",
    "MeetingCoverageSummary",
    "MeetingDetail",
    "build_artifact_detail_router",
    "build_meeting_artifacts_router",
    "build_meeting_detail_router",
]
