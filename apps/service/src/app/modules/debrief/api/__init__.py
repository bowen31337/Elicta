"""Debrief API package: the per-meeting artifact list and a single artifact by id (PRD FR-8.1 through FR-8.7).

Exposes no mounted router — both `build_meeting_artifacts_router` and
`build_artifact_detail_router` need a real `artifacts` table read injected
first — so this package is consumed directly by whoever wires the app
factory. `GET /api/meetings/{meeting_id}/artifacts` always returns 200 with
whatever `ArtifactSummary` list the lookup returns, including an empty list
for a meeting with no artifacts generated yet: a meeting's artifact list has
no "not found" state the way a single artifact route does, it is simply
empty until the debrief pipeline produces something. `GET
/api/artifacts/{artifact_id}` is that single artifact route: it 404s when
the id names no persisted row, and otherwise returns 200 with the full
`ArtifactDetail`, its `body` already carrying every citation it references
expanded rather than left as a bare utterance_id.
"""

from __future__ import annotations

from app.modules.debrief.api.models import ArtifactDetail, ArtifactSummary, ArtifactType
from app.modules.debrief.api.router import (
    GetArtifactById,
    GetMeetingArtifacts,
    build_artifact_detail_router,
    build_meeting_artifacts_router,
)

__all__ = [
    "ArtifactDetail",
    "ArtifactSummary",
    "ArtifactType",
    "GetArtifactById",
    "GetMeetingArtifacts",
    "build_artifact_detail_router",
    "build_meeting_artifacts_router",
]
