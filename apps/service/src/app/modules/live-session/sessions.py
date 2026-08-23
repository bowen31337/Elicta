"""`GET /api/sessions/live` — which meeting has a microphone open.

Nothing could answer this before. A session is started and never ended, since
there is no stop route, so the set of started sessions only grows and says
nothing about which one is being recorded. A meeting's own state stays
`planned` throughout. An operator with two windows open, or any tool outside
the browser, had no way to find the meeting actually in progress -- and the
panel and the capture screen keep their answer in the browser's storage, where
nothing else can reach it.

Audio arriving is the evidence, because it is the only thing that separates a
meeting being recorded from one started an hour ago and walked away from. What
is reported is what was seen and when: `receiving_audio` is a reading of the
clock against the last chunk, and a caller that would draw the line elsewhere
has the timestamp to draw it from.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

#: How recently audio must have arrived for a session to count as recording.
#: Chunks are uploaded every few seconds, so this is several missed ones rather
#: than a slow one -- long enough to survive a stall, short enough that a
#: meeting somebody stopped is not still described as live a minute later.
FRESH_AUDIO_SECONDS = 30.0


class LiveSession(BaseModel):
    """One session, and the evidence for calling it live."""

    session_id: str
    meeting_id: str
    started_at: datetime
    #: `None` when the session has never received a chunk -- which is what
    #: pressing Start with a microphone that reads nothing looks like.
    last_audio_at: datetime | None = None
    receiving_audio: bool


class LiveSessions(BaseModel):
    """Every session this process has started, freshest audio first."""

    sessions: list[LiveSession]


def build_live_sessions_router(
    read_sessions: Callable[[], Any],
    *,
    now: Callable[[], datetime] | None = None,
    fresh_seconds: float = FRESH_AUDIO_SECONDS,
) -> APIRouter:
    clock = now or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/api/sessions", tags=["live-session"])

    @router.get("/live", response_model=LiveSessions)
    async def live_sessions() -> LiveSessions:
        """Sessions this process started, with what is known about each."""

        moment = clock()
        rows = []
        for row in read_sessions():
            heard = row.get("last_audio_at")
            rows.append(
                LiveSession(
                    session_id=row["session_id"],
                    meeting_id=row["meeting_id"],
                    started_at=row["started_at"],
                    last_audio_at=heard,
                    receiving_audio=(
                        heard is not None
                        and (moment - heard).total_seconds() <= fresh_seconds
                    ),
                )
            )

        # Freshest audio first, and a session that has heard nothing last: a
        # caller asking "which meeting is being recorded" should be able to
        # read the answer off the top rather than sort for it.
        rows.sort(
            key=lambda row: row.last_audio_at.timestamp() if row.last_audio_at else float("-inf"),
            reverse=True,
        )
        return LiveSessions(sessions=rows)

    return router
