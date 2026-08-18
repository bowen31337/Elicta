"""HTTP surface for adding an attendee to a meeting (PRD FR-3.9, FR-3.10).

`build_meeting_attendees_router` takes an `add_attendee` callback rather than
importing the `attendees` table persistence layer directly, since that layer
does not live in this package (`app/modules/engagement/meetings`). Whoever
wires the app factory (out of this feature's footprint) supplies the real,
persistence-backed implementation -- assigning the row its id and attaching
it to `meeting_id` -- and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from .models import Attendee, AttendeeCreateRequest

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

    return router
