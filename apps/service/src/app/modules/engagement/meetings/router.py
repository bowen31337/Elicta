"""HTTP surface for adding attendees to a meeting (PRD FR-3.9, FR-3.10).

`build_meeting_attendees_router` takes an `add_attendee` callback rather than
importing the `attendees` table persistence layer directly, since that layer
does not live in this package (`app/modules/engagement/meetings`). Whoever
wires the app factory (out of this feature's footprint) supplies the real,
persistence-backed implementation -- assigning the row its id and attaching
it to `meeting_id` -- and mounts the returned router.

The calendar-invite endpoint pre-populates attendees from a meeting's
calendar invite where one is available (FR-3.9): each invitee becomes an
`AttendeeCreateRequest` carrying only a `display_name` -- a calendar invite
says who was invited, not their role, business function, decision
authority, or domain expertise (FR-3.10 fields), so those are left for a
person to fill in later -- and is persisted through the same `add_attendee`
callback used for a manually-added attendee, one row per invitee.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from .models import Attendee, AttendeeCreateRequest, CalendarInvite

AddAttendee = Callable[[str, AttendeeCreateRequest], Awaitable[Attendee]]


def build_meeting_attendees_router(add_attendee: AddAttendee) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["meeting-attendees"])

    @router.post(
        "/{meeting_id}/attendees",
        response_model=Attendee,
        status_code=201,
    )
    async def create_attendee(
        meeting_id: str, payload: AttendeeCreateRequest
    ) -> Attendee:
        return await add_attendee(meeting_id, payload)

    @router.post(
        "/{meeting_id}/attendees/from-calendar-invite",
        response_model=list[Attendee],
        status_code=201,
    )
    async def create_attendees_from_calendar_invite(
        meeting_id: str, payload: CalendarInvite
    ) -> list[Attendee]:
        attendees = []
        for invitee in payload.invitees:
            request = AttendeeCreateRequest(
                display_name=invitee.display_name or invitee.email
            )
            attendees.append(await add_attendee(meeting_id, request))
        return attendees

    return router
