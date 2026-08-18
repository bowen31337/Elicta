"""HTTP surface for listing an engagement's reference documents (PRD FR-3.4).

`build_engagement_documents_router` takes a callback rather than importing
the engagement/document persistence models directly, since that layer does
not live in this package (`app/modules/engagement/documents`) — same
reasoning as `app/modules/engagement/api/router.py`. Whoever wires the app
factory (out of this feature's footprint) supplies the real,
persistence-backed implementation and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, HTTPException

from .errors import EngagementNotFoundError
from .models import EngagementDocument, EngagementDocumentListResponse

ListEngagementDocuments = Callable[[str], Awaitable[Iterable[EngagementDocument]]]


def build_engagement_documents_router(
    list_documents: ListEngagementDocuments,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagement-documents"])

    @router.get(
        "/{engagement_id}/documents",
        response_model=EngagementDocumentListResponse,
        status_code=200,
    )
    async def get_engagement_documents(
        engagement_id: str,
    ) -> EngagementDocumentListResponse:
        try:
            documents = await list_documents(engagement_id)
        except EngagementNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return EngagementDocumentListResponse(
            engagement_id=engagement_id,
            documents=list(documents),
        )

    return router
