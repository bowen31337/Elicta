"""HTTP surface for starting a meeting's live capture session (PRD "Live Session" domain).

`build_live_session_router` takes a `StartSession` callback rather than
importing a concrete meeting store directly, since that persistence layer
does not live in this package (`app/modules/live-session`). Whoever wires
the app factory (out of this feature's footprint) supplies the real
implementation -- allocating the session and flipping the meeting into its
live state -- and mounts the returned router. `start_session` returns `None`
when the meeting does not exist, which the route turns into a 404 rather
than fabricating a session for a meeting that isn't there to capture.

Capture may not begin until all-party consent has been confirmed for the
meeting (PRD L1/L2, D3), so `admit_capture` is a second *required* callback
rather than an optional one: a gate that defaults to open is a gate a caller
can forget to close, and the failure would be silent. It is asked before
`start_session`, so a refused start allocates no session, and it answers
with a `CaptureAdmission` rather than a boolean so that "no such meeting"
(404) and "consent not confirmed" (403) stay distinct -- a 404 for a meeting
that does exist is the right answer for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum

from fastapi import APIRouter, HTTPException

from .models import SessionStart, SessionStop

StartSession = Callable[[str], Awaitable[SessionStart | None]]

#: Ends whatever live session a meeting has open. Answers `None` only when the
#: meeting itself is unknown -- a meeting with nothing open is not a failure,
#: and comes back as a `SessionStop` carrying no `session_id`.
StopSession = Callable[[str], Awaitable[SessionStop | None]]


class CaptureAdmission(str, Enum):
    """Whether this meeting may open a capture session, and if not, why not.

    Three-valued rather than a boolean because the two refusals mean
    different things to an operator and must not be collapsed: a meeting that
    does not exist is a 404, and a meeting that exists but has not had
    consent confirmed is a 403 that says so. Asked *before* `start_session`,
    so a refused start allocates nothing.
    """

    NOT_FOUND = "not_found"
    CONSENT_REQUIRED = "consent_required"
    ALLOWED = "allowed"


AdmitCapture = Callable[[str], Awaitable[CaptureAdmission]]

CONSENT_NOT_CONFIRMED = (
    "consent has not been confirmed for this meeting, so capture cannot begin"
)


def build_live_session_router(
    start_session: StartSession,
    admit_capture: AdmitCapture,
    stop_session: StopSession,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["live-session"])

    @router.post(
        "/{meeting_id}/session/start",
        response_model=SessionStart,
        status_code=200,
    )
    async def start_session_endpoint(meeting_id: str) -> SessionStart:
        admission = await admit_capture(meeting_id)
        if admission is CaptureAdmission.NOT_FOUND:
            raise HTTPException(status_code=404, detail="meeting not found")
        if admission is not CaptureAdmission.ALLOWED:
            raise HTTPException(status_code=403, detail=CONSENT_NOT_CONFIRMED)
        session = await start_session(meeting_id)
        if session is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return session

    @router.post(
        "/{meeting_id}/session/stop",
        response_model=SessionStop,
        status_code=200,
    )
    async def stop_session_endpoint(meeting_id: str) -> SessionStop:
        """End this meeting's live capture session.

        **This route is the fix for a button that did nothing.** The panel has
        posted here since the recording bar was added, and nothing has ever
        answered: the path was absent from the service, so every press was a
        404 that the panel turned into an `error` status it did not render.
        The operator saw the clock keep running. `stopSession.ts` was fully
        unit-tested the whole time, against a stubbed `fetch` -- and a stub
        answers whatever URL it is handed, so the suite was green about a
        route that did not exist.

        No request body. The panel used to send its own coverage summary here
        to be flushed as the session's final state, from the days when the
        panel was where coverage was counted. It is not any more: coverage is
        derived in the service from the meeting's own nudge dispositions,
        precisely so there is one answer in one place, and taking a second
        copy from the client would be re-opening that. A body sent anyway is
        ignored rather than refused, so an older panel still stops cleanly.

        Consent is deliberately not consulted. `admit_capture` guards
        *starting*; asking it here would mean a meeting whose consent was
        withdrawn mid-session could not be stopped, which is precisely
        backwards.
        """

        stopped = await stop_session(meeting_id)
        if stopped is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return stopped

    return router
