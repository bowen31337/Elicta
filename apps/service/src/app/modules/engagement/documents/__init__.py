"""Engagement documents package: the reference document list (PRD FR-3.4).

Exposes `build_engagement_documents_router`, which mounts
`GET /api/engagements/{engagement_id}/documents` — the list of reference
documents attached to an engagement, each with its required status tag
(`ground truth`, `hypothesis`, or `superseded`).
"""

from __future__ import annotations

from .errors import EngagementNotFoundError
from .models import DocumentStatus, EngagementDocument, EngagementDocumentListResponse
from .router import ListEngagementDocuments, build_engagement_documents_router

__all__ = [
    "DocumentStatus",
    "EngagementDocument",
    "EngagementDocumentListResponse",
    "EngagementNotFoundError",
    "ListEngagementDocuments",
    "build_engagement_documents_router",
]
