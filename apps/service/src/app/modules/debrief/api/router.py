"""HTTP surface for a meeting's artifact list (PRD FR-8.1 through FR-8.6).

`build_meeting_artifacts_router` takes the artifact-list lookup as an
injected callable rather than importing a concrete persistence layer
directly, since the `artifacts` table read does not live in this package
(`app/modules/debrief/api`). Whoever wires the app factory (out of this
feature's footprint) supplies the real, persistence-backed implementation
and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from .models import ArtifactSummary

GetMeetingArtifacts = Callable[[str], Awaitable[list[ArtifactSummary]]]


def build_meeting_artifacts_router(get_artifacts: GetMeetingArtifacts) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["debrief-artifacts"])

    @router.get(
        "/{meeting_id}/artifacts",
        response_model=list[ArtifactSummary],
        status_code=200,
    )
    async def list_meeting_artifacts(meeting_id: str) -> list[ArtifactSummary]:
        return await get_artifacts(meeting_id)

    return router
