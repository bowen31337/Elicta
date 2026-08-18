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

`get_engagement` and `get_document_count` are optional injected dependencies,
mirroring `get_alignment` in `asr-record/router.py`: a caller that hasn't
wired engagement or document persistence yet can still mount this router for
create/update alone. When both are supplied, `GET /{engagement_id}` combines
the engagement's own context fields with the document count from the sibling
`documents` package and the context-completeness score `completeness.py`
computes from those fields — a single read spanning what would otherwise be
two separate lookups.

`list_engagements` is likewise optional and, when supplied, backs
`GET /api/engagements`: a paginated list of engagements for the signed-in
delivery team. Scoping the list to the caller's team is an authentication
concern that lives outside this feature's footprint
(`app/modules/engagement/api`) — `list_engagements` is expected to already be
closed over whatever caller identity the wiring layer resolves, the same way
`create_engagement`/`update_engagement` take no caller identity of their own.
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query

from app.modules.engagement.api.completeness import compute_context_completeness_score
from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementCreateResponse,
    EngagementDetailResponse,
    EngagementListResponse,
    EngagementRecord,
    EngagementSummary,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)

CreateEngagement = Callable[[EngagementCreateRequest], Awaitable[str]]
UpdateEngagement = Callable[
    [str, EngagementUpdateRequest], Awaitable[EngagementUpdateResponse | None]
]
GetEngagement = Callable[[str], Awaitable[EngagementRecord | None]]
GetDocumentCount = Callable[[str], Awaitable[int]]
ListEngagements = Callable[[int, int], Awaitable[tuple[list[EngagementSummary], int]]]


def build_engagement_router(
    create_engagement: CreateEngagement,
    update_engagement: UpdateEngagement,
    get_engagement: GetEngagement | None = None,
    get_document_count: GetDocumentCount | None = None,
    list_engagements: ListEngagements | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagements"])

    if list_engagements is not None:

        @router.get(
            "",
            response_model=EngagementListResponse,
            status_code=200,
        )
        async def list_engagements_endpoint(
            page: int = Query(default=1, ge=1),
            page_size: int = Query(default=20, ge=1, le=100),
        ) -> EngagementListResponse:
            items, total = await list_engagements(page, page_size)
            return EngagementListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
            )

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

    if get_engagement is not None:

        @router.get(
            "/{engagement_id}",
            response_model=EngagementDetailResponse,
            status_code=200,
        )
        async def get_engagement_endpoint(engagement_id: str) -> EngagementDetailResponse:
            engagement = await get_engagement(engagement_id)
            if engagement is None:
                raise HTTPException(status_code=404, detail="engagement not found")
            document_count = (
                await get_document_count(engagement_id)
                if get_document_count is not None
                else 0
            )
            return EngagementDetailResponse(
                engagement_id=engagement_id,
                client_organisation=engagement.client_organisation,
                sector=engagement.sector,
                commercial_context=engagement.commercial_context,
                purpose=engagement.purpose,
                scope_boundary=engagement.scope_boundary,
                target_requirements_template=engagement.target_requirements_template,
                document_count=document_count,
                context_completeness_score=compute_context_completeness_score(engagement),
            )

    return router
