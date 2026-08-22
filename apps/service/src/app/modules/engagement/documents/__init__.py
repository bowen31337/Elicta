"""Engagement documents package: the reference document list and link
attachment (PRD FR-3.2, FR-3.4).

Exposes `build_engagement_documents_router`, which mounts
`GET /api/engagements/{engagement_id}/documents` — the list of reference
documents attached to an engagement, each with its required status tag
(`ground truth`, `hypothesis`, or `superseded`) — and
`POST /api/engagements/{engagement_id}/documents` to upload a new one as a
multipart file (PRD FR-3.2), rejecting a request that omits the required
status tag with a 422 naming the field (PRD FR-3.4). Also exposes
`build_document_status_router`, which mounts
`PATCH /api/documents/{document_id}/status` to retag a document's status.

Also exposes `build_reference_document_link_router`, which mounts
`POST /api/engagements/{engagement_id}/documents/link` (PRD FR-3.2): fetches
the body of a SharePoint or Teams link and, once fetched, persists it into
the `reference_documents` table via the injected `attach_document`
callback. A link whose host isn't SharePoint or Teams is rejected with a
422 naming the field.
"""

from __future__ import annotations

from .errors import (
    DocumentNotFoundError,
    EngagementNotFoundError,
    ReferenceDocumentFetchError,
)
from .link import classify_reference_link_host
from .models import (
    DocumentLinkAttachmentRequest,
    DocumentStatus,
    DocumentStatusUpdateRequest,
    DocumentUploadRequest,
    EngagementDocument,
    EngagementDocumentListResponse,
    ReferenceDocument,
)
from .router import (
    AttachReferenceDocument,
    FetchReferenceDocumentBody,
    ListEngagementDocuments,
    UpdateDocumentStatus,
    UploadEngagementDocument,
    build_document_delete_router,
    build_document_status_router,
    build_engagement_documents_router,
    build_reference_document_link_router,
    build_vocabulary_delete_router,
)

__all__ = [
    "AttachReferenceDocument",
    "DocumentLinkAttachmentRequest",
    "DocumentNotFoundError",
    "DocumentStatus",
    "DocumentStatusUpdateRequest",
    "DocumentUploadRequest",
    "EngagementDocument",
    "EngagementDocumentListResponse",
    "EngagementNotFoundError",
    "FetchReferenceDocumentBody",
    "ListEngagementDocuments",
    "ReferenceDocument",
    "ReferenceDocumentFetchError",
    "UpdateDocumentStatus",
    "UploadEngagementDocument",
    "build_document_delete_router",
    "build_vocabulary_delete_router",
    "build_document_status_router",
    "build_engagement_documents_router",
    "build_reference_document_link_router",
    "classify_reference_link_host",
]
