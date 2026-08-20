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

from .models import SessionStart

StartSession = Callable[[str], Awaitable[SessionStart | None]]


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
    start_session: StartSession, admit_capture: AdmitCapture
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

    return router
