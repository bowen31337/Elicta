"""HTTP surface for an engagement's reference documents (PRD FR-3.2, FR-3.4).

`build_engagement_documents_router`, `build_document_status_router`, and
`build_reference_document_link_router` take callbacks rather than importing
the engagement/document persistence models directly, since that layer does
not live in this package (`app/modules/engagement/documents`) — same
reasoning as `app/modules/engagement/api/router.py`. Whoever wires the app
factory (out of this feature's footprint) supplies the real,
persistence-backed implementations and mounts the returned routers.

The upload endpoint's required-status-tag validation (PRD FR-3.4) needs no
handler code of its own: `DocumentUploadRequest.status` has no default, so
FastAPI's request-body validation rejects a payload that omits it with a
422 before `upload_document` is ever called, and the response body already
names the missing field. `build_reference_document_link_router`'s
`DocumentLinkAttachmentRequest.url` validator works the same way for an
unrecognized host (PRD FR-3.2).

`build_reference_document_link_router` splits the FR-3.2 link-attachment
flow into two collaborators rather than one: `fetch_body` retrieves the
linked document's content, and `attach_document` is only called with that
content once the fetch succeeds, so a fetch failure (`ReferenceDocumentFetchError`)
never reaches — and never persists through — the callback that writes the
`reference_documents` row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, HTTPException

from .errors import (
    DocumentNotFoundError,
    EngagementNotFoundError,
    ReferenceDocumentFetchError,
)
from .models import (
    DocumentLinkAttachmentRequest,
    DocumentStatus,
    DocumentStatusUpdateRequest,
    DocumentUploadRequest,
    EngagementDocument,
    EngagementDocumentListResponse,
    ReferenceDocument,
)

ListEngagementDocuments = Callable[[str], Awaitable[Iterable[EngagementDocument]]]
UploadEngagementDocument = Callable[
    [str, DocumentUploadRequest], Awaitable[EngagementDocument]
]
UpdateDocumentStatus = Callable[[str, DocumentStatus], Awaitable[EngagementDocument]]
FetchReferenceDocumentBody = Callable[[str], Awaitable[str]]
AttachReferenceDocument = Callable[
    [str, DocumentLinkAttachmentRequest, str], Awaitable[ReferenceDocument]
]


def build_engagement_documents_router(
    list_documents: ListEngagementDocuments,
    upload_document: UploadEngagementDocument,
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

    @router.post(
        "/{engagement_id}/documents",
        response_model=EngagementDocument,
        status_code=201,
    )
    async def upload_engagement_document(
        engagement_id: str, payload: DocumentUploadRequest
    ) -> EngagementDocument:
        try:
            return await upload_document(engagement_id, payload)
        except EngagementNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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


def build_reference_document_link_router(
    fetch_body: FetchReferenceDocumentBody,
    attach_document: AttachReferenceDocument,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagement-documents"])

    @router.post(
        "/{engagement_id}/documents/link",
        response_model=ReferenceDocument,
        status_code=201,
    )
    async def attach_reference_document_link(
        engagement_id: str, payload: DocumentLinkAttachmentRequest
    ) -> ReferenceDocument:
        try:
            body = await fetch_body(payload.url)
        except ReferenceDocumentFetchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            return await attach_document(engagement_id, payload, body)
        except EngagementNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
