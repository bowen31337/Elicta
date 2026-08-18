"""HTTP surface for an engagement's reference documents (PRD FR-3.4).

Both `build_engagement_documents_router` and `build_document_status_router`
take a callback rather than importing the engagement/document persistence
models directly, since that layer does not live in this package
(`app/modules/engagement/documents`) — same reasoning as
`app/modules/engagement/api/router.py`. Whoever wires the app factory (out
of this feature's footprint) supplies the real, persistence-backed
implementation and mounts the returned routers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, HTTPException

from .errors import DocumentNotFoundError, EngagementNotFoundError
from .models import (
    DocumentStatus,
    DocumentStatusUpdateRequest,
    EngagementDocument,
    EngagementDocumentListResponse,
)

ListEngagementDocuments = Callable[[str], Awaitable[Iterable[EngagementDocument]]]
UpdateDocumentStatus = Callable[[str, DocumentStatus], Awaitable[EngagementDocument]]


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


def build_document_status_router(
    update_status: UpdateDocumentStatus,
) -> APIRouter:
    router = APIRouter(prefix="/api/documents", tags=["engagement-documents"])

    @router.patch(
        "/{document_id}/status",
        response_model=EngagementDocument,
        status_code=200,
    )
    async def patch_document_status(
        document_id: str, body: DocumentStatusUpdateRequest
    ) -> EngagementDocument:
        try:
            return await update_status(document_id, body.status)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
