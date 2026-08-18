"""Debrief API package: the per-meeting artifact list (PRD FR-8.1 through FR-8.6).

Exposes no mounted router — `build_meeting_artifacts_router` needs a real
`artifacts` table read injected first — so this package is consumed directly
by whoever wires the app factory. `GET /api/meetings/{meeting_id}/artifacts`
always returns 200 with whatever `ArtifactSummary` list the lookup returns,
including an empty list for a meeting with no artifacts generated yet: a
meeting's artifact list has no "not found" state the way a single artifact
route does, it is simply empty until the debrief pipeline produces something.
"""

from __future__ import annotations

from app.modules.debrief.api.models import ArtifactSummary, ArtifactType
from app.modules.debrief.api.router import (
    GetMeetingArtifacts,
    build_meeting_artifacts_router,
)

__all__ = [
    "ArtifactSummary",
    "ArtifactType",
    "GetMeetingArtifacts",
    "build_meeting_artifacts_router",
]
