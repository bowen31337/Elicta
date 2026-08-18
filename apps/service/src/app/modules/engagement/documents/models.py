"""Domain and DTOs for an engagement's reference documents (PRD FR-3.2, FR-3.4).

Every reference document must carry a status tag: `ground truth`,
`hypothesis`, or `superseded`. That tag governs how later features treat the
document — contradiction triggers fire only against `ground truth`,
`hypothesis` documents generate verification questions instead, and
`superseded` documents remain indexed for background but never trigger (PRD
§8.3 rationale for FR-3.4). This package only lists documents and their
tags; it does not implement that downstream triggering behaviour.

`DocumentLinkAttachmentRequest` and `ReferenceDocument` cover FR-3.2's other
intake path: attaching a reference document by SharePoint or Teams link
rather than direct upload. `ReferenceDocument` mirrors the persisted
`reference_documents` row (`id`, `engagement_id`, `status`, `source_uri`)
rather than `EngagementDocument` above, since the link-attachment flow has
no document `name` to carry — only the link it was fetched from.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .link import classify_reference_link_host


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
    """Assembled from a multipart upload (POST .../documents): the file's
    name, its raw bytes, and the required status tag (PRD FR-3.2, FR-3.4).

    `status` has no default: every reference document must carry one of the
    three status tags at upload time (PRD FR-3.4), so a request that omits
    the `status` form field is a validation failure rather than something to
    default away — FastAPI's `Form(...)` handling turns that into a 422
    whose `detail` names the offending field, giving the field-level error
    message FR-3.4 calls for.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: DocumentStatus
    content: bytes


class DocumentLinkAttachmentRequest(BaseModel):
    """Body for attaching a reference document by link (PRD FR-3.2).

    `url` is validated against known SharePoint and Microsoft Teams
    hostnames rather than accepted as any URL: FR-3.2 asks specifically for
    those two sources, so an unsupported host fails validation with a 422
    naming the field, the same style FR-3.4 uses for a missing `status`.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    status: DocumentStatus

    @field_validator("url")
    @classmethod
    def _require_sharepoint_or_teams_host(cls, value: str) -> str:
        if classify_reference_link_host(value) is None:
            raise ValueError(
                "url must be a SharePoint (*.sharepoint.com) or "
                "Microsoft Teams (teams.microsoft.com) link"
            )
        return value


class ReferenceDocument(BaseModel):
    """One reference document row as persisted from a link attachment
    (mirrors the `reference_documents` table: PRD FR-3.2)."""

    id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    status: DocumentStatus
    source_uri: str = Field(min_length=1)
