"""HTTP surface for engagement creation (PRD FR-3.1).

`build_engagement_router` takes a `create_engagement` callback rather than
importing an engagement persistence model directly, since that layer does
not live in this package (`app/modules/engagement/api`). Whoever wires the
app factory (out of this feature's footprint) supplies the real,
persistence-backed implementation and mounts the returned router.
"""

from collections.abc import Awaitable, Callable

from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementCreateResponse,
)
from fastapi import APIRouter

CreateEngagement = Callable[[EngagementCreateRequest], Awaitable[str]]


def build_engagement_router(create_engagement: CreateEngagement) -> APIRouter:
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

    return router
