"""HTTP surface for starting a meeting's live capture session (PRD "Live Session" domain).

`build_live_session_router` takes a `StartSession` callback rather than
importing a concrete meeting store directly, since that persistence layer
does not live in this package (`app/modules/live-session`). Whoever wires
the app factory (out of this feature's footprint) supplies the real
implementation -- allocating the session and flipping the meeting into its
live state -- and mounts the returned router. `start_session` returns `None`
when the meeting does not exist, which the route turns into a 404 rather
than fabricating a session for a meeting that isn't there to capture.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import SessionStart

StartSession = Callable[[str], Awaitable[SessionStart | None]]


def build_live_session_router(start_session: StartSession) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["live-session"])

    @router.post(
        "/{meeting_id}/session/start",
        response_model=SessionStart,
        status_code=200,
    )
    async def start_session_endpoint(meeting_id: str) -> SessionStart:
        session = await start_session(meeting_id)
        if session is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return session

    return router
