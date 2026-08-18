"""Request/response DTOs for the meeting attendees API (PRD FR-3.9, FR-3.10).

`AttendeeCreateRequest` mirrors the `attendees` table's structured columns:
`role`, `business_function`, `decision_authority`, `domain_expertise`, plus
the optional `display_name` a calendar invite pre-populates (FR-3.9). FR-3.10
requires attendee profiles to be captured through structured fields only,
and explicitly rules out a free-text personal assessment field -- a prose
write-up invites discoverable, subjective assessments of named individuals
that the model would then act on. An attendee can therefore be created from
the four structured fields alone, with no name required; `extra="forbid"`
enforces the "structured only" half by construction, since a caller cannot
smuggle a free-text field like `notes` or `assessment` in alongside them.
`domain_expertise` is a list rather than a scalar since one attendee can
carry more than one area of expertise, mirroring the JSONB column it's
persisted into.

`Attendee` mirrors the same table row in full, adding the identity
(`id`, `meeting_id`) that only exists once the row has been persisted.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AttendeeCreateRequest(BaseModel):
    """One attendee's structured profile, captured with no free-text assessment field (PRD FR-3.10)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1)
    role: str | None = None
    business_function: str | None = None
    decision_authority: str | None = None
    domain_expertise: list[str] = Field(default_factory=list)


class Attendee(BaseModel):
    """A persisted `attendees` row (PRD FR-3.9, FR-3.10)."""

    id: str
    meeting_id: str
    display_name: str | None = None
    role: str | None = None
    business_function: str | None = None
    decision_authority: str | None = None
    domain_expertise: list[str] = Field(default_factory=list)
