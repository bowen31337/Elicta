"""Request/response DTOs for the engagement creation API (PRD FR-3.1)."""

from pydantic import BaseModel, Field


class EngagementCreateRequest(BaseModel):
    """Client background captured once, at engagement creation (PRD FR-3.1)."""

    client_organisation: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    commercial_context: str = Field(min_length=1)


class EngagementCreateResponse(BaseModel):
    engagement_id: str
