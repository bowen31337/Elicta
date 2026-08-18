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

from pydantic import BaseModel, ConfigDict, Field


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


class DocumentStatusUpdateRequest(BaseModel):
    """Body for retagging a document's status (PATCH .../documents/{id}/status)."""

    status: DocumentStatus


class DocumentUploadRequest(BaseModel):
    """Body for uploading a reference document (POST .../documents).

    `status` has no default: every reference document must carry one of the
    three status tags at upload time (PRD FR-3.4), so omitting it is a
    validation failure rather than something to default away. FastAPI's
    standard request-validation handling turns a missing required field
    into a 422 whose `detail` names the offending field (`loc`), giving the
    field-level error message FR-3.4 calls for.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: DocumentStatus
