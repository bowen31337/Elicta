"""HTTP surface for a meeting's artifact list and a single artifact by id (PRD FR-8.1 through FR-8.7).

`build_meeting_artifacts_router` and `build_artifact_detail_router` both take
their lookup as an injected callable rather than importing a concrete
persistence layer directly, since the `artifacts` table read does not live in
this package (`app/modules/debrief/api`). Whoever wires the app factory (out
of this feature's footprint) supplies the real, persistence-backed
implementation and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import ArtifactDetail, ArtifactSummary

GetMeetingArtifacts = Callable[[str], Awaitable[list[ArtifactSummary]]]
GetArtifactById = Callable[[str], Awaitable[ArtifactDetail | None]]


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


def build_artifact_detail_router(get_artifact: GetArtifactById) -> APIRouter:
    """Build the single-artifact-by-id read router (PRD FR-8.1 through FR-8.7).

    Unlike the meeting artifact list, which is simply empty until the
    debrief pipeline produces something, a single artifact looked up by an
    `id` that doesn't name a persisted row has a real "not found" state, so
    this 404s instead of returning an empty or null body.
    """

    router = APIRouter(prefix="/api/artifacts", tags=["debrief-artifacts"])

    @router.get("/{artifact_id}", response_model=ArtifactDetail, status_code=200)
    async def get_artifact_detail(artifact_id: str) -> ArtifactDetail:
        artifact = await get_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return artifact

    return router
