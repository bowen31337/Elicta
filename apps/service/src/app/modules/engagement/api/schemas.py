"""Request/response DTOs for the engagement creation and update APIs (PRD FR-3.1, FR-3.5)."""

from pydantic import BaseModel, Field, model_validator


class EngagementCreateRequest(BaseModel):
    """Client background captured once, at engagement creation (PRD FR-3.1)."""

    client_organisation: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    commercial_context: str = Field(min_length=1)


class EngagementCreateResponse(BaseModel):
    engagement_id: str


class EngagementUpdateRequest(BaseModel):
    """Engagement purpose, scope boundary, and target requirements template (PRD FR-3.5).

    All three fields are optional so a caller can update any subset of them
    in a single PATCH; at least one must be supplied, since a PATCH with
    nothing to change has no meaningful effect to report as a 200.
    """

    purpose: str | None = Field(default=None, min_length=1)
    scope_boundary: str | None = Field(default=None, min_length=1)
    target_requirements_template: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "EngagementUpdateRequest":
        if self.purpose is None and self.scope_boundary is None and self.target_requirements_template is None:
            raise ValueError(
                "at least one of purpose, scope_boundary, target_requirements_template must be provided"
            )
        return self


class EngagementUpdateResponse(BaseModel):
    engagement_id: str
    purpose: str | None = None
    scope_boundary: str | None = None
    target_requirements_template: str | None = None


class EngagementRecord(BaseModel):
    """The engagement's own context fields, as persisted (PRD FR-3.1, FR-3.5).

    Carries exactly the fields `EngagementCreateRequest` and
    `EngagementUpdateRequest` capture — nothing document- or vocabulary-related
    — since those live in sibling packages outside this feature's footprint.
    `GetEngagement` returns this so `compute_context_completeness_score`
    (`completeness.py`) has every field it needs without importing a
    persistence model.
    """

    client_organisation: str
    sector: str
    commercial_context: str
    purpose: str | None = None
    scope_boundary: str | None = None
    target_requirements_template: str | None = None


class EngagementDetailResponse(BaseModel):
    """A single engagement with its document count and context-completeness score."""

    engagement_id: str
    client_organisation: str
    sector: str
    commercial_context: str
    purpose: str | None = None
    scope_boundary: str | None = None
    target_requirements_template: str | None = None
    document_count: int
    context_completeness_score: float
