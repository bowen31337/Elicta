"""Domain and DTOs for an engagement's reference documents (PRD FR-3.4).

Every reference document must carry a status tag: `ground truth`,
`hypothesis`, or `superseded`. That tag governs how later features treat the
document — contradiction triggers fire only against `ground truth`,
`hypothesis` documents generate verification questions instead, and
`superseded` documents remain indexed for background but never trigger (PRD
§8.3 rationale for FR-3.4). This package only lists documents and their
tags; it does not implement that downstream triggering behaviour.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """Status tag required on every reference document (PRD FR-3.4)."""

    GROUND_TRUTH = "ground truth"
    HYPOTHESIS = "hypothesis"
    SUPERSEDED = "superseded"


class EngagementDocument(BaseModel):
    """One reference document attached to an engagement, with its status tag."""

    document_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: DocumentStatus


class EngagementDocumentListResponse(BaseModel):
    """The full document list for one engagement (GET .../documents)."""

    engagement_id: str = Field(min_length=1)
    documents: list[EngagementDocument]
