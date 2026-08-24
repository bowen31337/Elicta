"""HTTP surface for meeting attendees and per-meeting session setup (PRD FR-3.8, FR-3.9, FR-3.10).

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

`build_meeting_router` takes an `update_meeting` callback for the same
reason: it persists this session's purpose and target template sections
(FR-3.8) against whatever table backs a meeting, which also doesn't live in
this package. `update_meeting` returns `None` when the meeting does not
exist, which the PATCH route turns into a 404 rather than a 200 with a
fabricated body -- mirroring `app/modules/engagement/api/router.py`'s
handling of an unknown engagement.

`build_meeting_router` also takes `create_meeting` and
`get_engagement_context` callbacks for the meeting-creation route (FR-3.7):
`get_engagement_context` looks up the engagement a new meeting belongs to
and returns `None` when it does not exist, which the POST route turns into
a 404 before ever calling `create_meeting` -- a meeting cannot be created
for an engagement that isn't there to inherit context from. When the
engagement is found, its context is attached to the 201 response as
`engagement_context` so the caller can confirm what was inherited rather
than re-enter it (FR-3.7), and only then is `create_meeting` called to
persist the new row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import (
    Attendee,
    AttendeeCreateRequest,
    CalendarInvite,
    EngagementContext,
    MeetingCreateRequest,
    MeetingCreateResponse,
    MeetingListResponse,
    MeetingSummary,
    MeetingUpdateRequest,
    MeetingUpdateResponse,
)

AddAttendee = Callable[[str, AttendeeCreateRequest], Awaitable[Attendee]]
UpdateMeeting = Callable[
    [str, MeetingUpdateRequest], Awaitable[MeetingUpdateResponse | None]
]
CreateMeeting = Callable[[MeetingCreateRequest], Awaitable[str]]
GetEngagementContext = Callable[[str], Awaitable[EngagementContext | None]]
ListMeetings = Callable[[str], Awaitable[list[MeetingSummary] | None]]
DeleteMeeting = Callable[[str], Awaitable[bool]]


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


def build_meeting_router(
    create_meeting: CreateMeeting,
    get_engagement_context: GetEngagementContext,
    update_meeting: UpdateMeeting,
    delete_meeting: DeleteMeeting | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["meetings"])

    @router.post(
        "",
        response_model=MeetingCreateResponse,
        status_code=201,
    )
    async def create_meeting_endpoint(
        payload: MeetingCreateRequest,
    ) -> MeetingCreateResponse:
        engagement_context = await get_engagement_context(payload.engagement_id)
        if engagement_context is None:
            raise HTTPException(status_code=404, detail="engagement not found")
        meeting_id = await create_meeting(payload)
        return MeetingCreateResponse(
            meeting_id=meeting_id,
            engagement_id=payload.engagement_id,
            state="planned",
            capture_mode=payload.capture_mode,
            scheduled_at=payload.scheduled_at,
            engagement_context=engagement_context,
        )

    @router.patch(
        "/{meeting_id}",
        response_model=MeetingUpdateResponse,
        status_code=200,
    )
    async def update_meeting_endpoint(
        meeting_id: str,
        payload: MeetingUpdateRequest,
    ) -> MeetingUpdateResponse:
        updated = await update_meeting(meeting_id, payload)
        if updated is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return updated

    if delete_meeting is not None:

        @router.delete("/{meeting_id}", status_code=204)
        async def delete_meeting_endpoint(meeting_id: str) -> None:
            """Take a meeting out of view (soft).

            Optional for the same reason the engagement router's delete is:
            whether a removal is even offered belongs to whoever assembles the
            app, and the tests that build this router to exercise create and
            update should not have to invent a way to destroy things.

            The row stays, marked, and so does everything hanging off it — the
            consent record, the transcripts, the audio-destruction events. A
            removal here is about a list an operator has to read, not about
            erasing the record of a meeting that actually happened.
            """

            if not await delete_meeting(meeting_id):
                raise HTTPException(status_code=404, detail="meeting not found")

    return router


def build_engagement_meetings_router(list_meetings: ListMeetings) -> APIRouter:
    """Build the meetings-of-an-engagement list route.

    Mounted under `/api/engagements` rather than `/api/meetings` because the
    engagement is the key: this answers "which meetings belong to this
    engagement", the read that lets an operator find their way back to work
    they started in an earlier session. Without it the only way to hold a
    meeting id was to be the caller that created it.

    `list_meetings` returns `None` for an engagement that does not exist,
    which becomes a 404 — the same shape `update_meeting` uses above. An
    engagement that exists with no meetings yet returns an empty list and a
    200: a brand-new engagement is a normal state, not an error.
    """

    router = APIRouter(prefix="/api/engagements", tags=["meetings"])

    @router.get(
        "/{engagement_id}/meetings",
        response_model=MeetingListResponse,
        status_code=200,
    )
    async def list_engagement_meetings(engagement_id: str) -> MeetingListResponse:
        meetings = await list_meetings(engagement_id)
        if meetings is None:
            raise HTTPException(status_code=404, detail="engagement not found")
        return MeetingListResponse(engagement_id=engagement_id, meetings=meetings)

    return router
