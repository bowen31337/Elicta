"""Engagement documents package: the reference document list (PRD FR-3.4).

Exposes `build_engagement_documents_router`, which mounts
`GET /api/engagements/{engagement_id}/documents` — the list of reference
documents attached to an engagement, each with its required status tag
(`ground truth`, `hypothesis`, or `superseded`) — and
`POST /api/engagements/{engagement_id}/documents` to upload a new one,
rejecting a payload that omits the required status tag with a 422 naming
the field (PRD FR-3.4). Also exposes `build_document_status_router`, which
mounts `PATCH /api/documents/{document_id}/status` to retag a document's
status.
"""

from __future__ import annotations

from .errors import DocumentNotFoundError, EngagementNotFoundError
from .models import (
    DocumentStatus,
    DocumentStatusUpdateRequest,
    DocumentUploadRequest,
    EngagementDocument,
    EngagementDocumentListResponse,
)
from .router import (
    ListEngagementDocuments,
    UpdateDocumentStatus,
    UploadEngagementDocument,
    build_document_status_router,
    build_engagement_documents_router,
)

__all__ = [
    "DocumentNotFoundError",
    "DocumentStatus",
    "DocumentStatusUpdateRequest",
    "DocumentUploadRequest",
    "EngagementDocument",
    "EngagementDocumentListResponse",
    "EngagementNotFoundError",
    "ListEngagementDocuments",
    "UpdateDocumentStatus",
    "UploadEngagementDocument",
    "build_document_status_router",
    "build_engagement_documents_router",
]
