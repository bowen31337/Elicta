"""Request/response DTOs for the meeting attendees and meeting update APIs (PRD FR-3.8, FR-3.9, FR-3.10).

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

`CalendarInvitee` and `CalendarInvite` model the calendar invite itself,
where one is available for a meeting (FR-3.9): a list of invited people,
each identified by `email` and an optional friendlier `display_name`.

`MeetingUpdateRequest`/`MeetingUpdateResponse` cover FR-3.8: per-meeting
setup that keeps to a "confirm rather than re-enter" workflow (FR-3.7) is
supposed to take under two minutes, so `session_purpose` and
`target_template_sections` are both optional -- a caller updates whichever
subset changed -- but at least one must be supplied, since a PATCH with
nothing to change has no meaningful effect to report as a 200.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class CalendarInvitee(BaseModel):
    """One person invited via a calendar invite (PRD FR-3.9).

    `email` is the only field a calendar invite reliably carries for every
    invitee; `display_name` is the friendlier label most calendar systems
    also include. Neither implies any of the structured profile fields
    (`role`, `business_function`, `decision_authority`, `domain_expertise`)
    from FR-3.10 -- those are unknowable from an invite and are filled in
    later, so a pre-populated attendee starts with only a name.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1)
    display_name: str | None = Field(default=None, min_length=1)


class CalendarInvite(BaseModel):
    """A calendar invite's invitee list, used to pre-populate meeting attendees (PRD FR-3.9)."""

    model_config = ConfigDict(extra="forbid")

    invitees: list[CalendarInvitee] = Field(default_factory=list)


class MeetingUpdateRequest(BaseModel):
    """This session's purpose and target template sections (PRD FR-3.8).

    Both fields are optional so a caller can update either one alone; at
    least one must be supplied, since a PATCH with nothing to change has no
    meaningful effect to report as a 200.
    """

    model_config = ConfigDict(extra="forbid")

    session_purpose: str | None = Field(default=None, min_length=1)
    target_template_sections: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> MeetingUpdateRequest:
        if self.session_purpose is None and self.target_template_sections is None:
            raise ValueError(
                "at least one of session_purpose, target_template_sections must be provided"
            )
        return self


class MeetingUpdateResponse(BaseModel):
    """A meeting's session purpose and target template sections after a PATCH (PRD FR-3.8)."""

    meeting_id: str
    session_purpose: str | None = None
    target_template_sections: list[str] | None = None
