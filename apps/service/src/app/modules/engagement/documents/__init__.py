"""Engagement documents package: the reference document list (PRD FR-3.4).

Exposes `build_engagement_documents_router`, which mounts
`GET /api/engagements/{engagement_id}/documents` — the list of reference
documents attached to an engagement, each with its required status tag
(`ground truth`, `hypothesis`, or `superseded`) — and
`build_document_status_router`, which mounts
`PATCH /api/documents/{document_id}/status` to retag a document's status.
"""

from __future__ import annotations

from .errors import DocumentNotFoundError, EngagementNotFoundError
from .models import (
    DocumentStatus,
    DocumentStatusUpdateRequest,
    EngagementDocument,
    EngagementDocumentListResponse,
)
from .router import (
    ListEngagementDocuments,
    UpdateDocumentStatus,
    build_document_status_router,
    build_engagement_documents_router,
)

__all__ = [
    "DocumentNotFoundError",
    "DocumentStatus",
    "DocumentStatusUpdateRequest",
    "EngagementDocument",
    "EngagementDocumentListResponse",
    "EngagementNotFoundError",
    "ListEngagementDocuments",
    "UpdateDocumentStatus",
    "build_document_status_router",
    "build_engagement_documents_router",
]
