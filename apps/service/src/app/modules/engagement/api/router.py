"""HTTP surface for engagement creation and update (PRD FR-3.1, FR-3.5).

`build_engagement_router` takes `create_engagement` and `update_engagement`
callbacks rather than importing an engagement persistence model directly,
since that layer does not live in this package
(`app/modules/engagement/api`). Whoever wires the app factory (out of this
feature's footprint) supplies the real, persistence-backed implementations
and mounts the returned router.

`update_engagement` returns `None` when the engagement does not exist, which
the PATCH route turns into a 404 rather than a 200 with a fabricated body —
mirroring the not-found handling every other router in this codebase uses
(`debrief/artifacts/router.py`).
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementCreateResponse,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)

CreateEngagement = Callable[[EngagementCreateRequest], Awaitable[str]]
UpdateEngagement = Callable[
    [str, EngagementUpdateRequest], Awaitable[EngagementUpdateResponse | None]
]


def build_engagement_router(
    create_engagement: CreateEngagement,
    update_engagement: UpdateEngagement,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagements"])

    @router.post(
        "",
        response_model=EngagementCreateResponse,
        status_code=201,
    )
    async def create_engagement_endpoint(
        payload: EngagementCreateRequest,
    ) -> EngagementCreateResponse:
        engagement_id = await create_engagement(payload)
        return EngagementCreateResponse(engagement_id=engagement_id)

    @router.patch(
        "/{engagement_id}",
        response_model=EngagementUpdateResponse,
        status_code=200,
    )
    async def update_engagement_endpoint(
        engagement_id: str,
        payload: EngagementUpdateRequest,
    ) -> EngagementUpdateResponse:
        updated = await update_engagement(engagement_id, payload)
        if updated is None:
            raise HTTPException(status_code=404, detail="engagement not found")
        return updated

    return router
