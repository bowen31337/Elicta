"""The live session stream the panel renders from.

The panel is a second screen: the desktop captures, and this stream is how
what it heard reaches whatever is displaying the nudges. Two event types
travel on it — `coverage`, the current summary rather than a log of changes,
and `nudge`, one surfaced question.

Server-sent events rather than a websocket, deliberately. The traffic is one
way, it is text, and it has to survive a laptop lid closing mid-meeting: SSE
reconnects on its own, where a websocket needs reconnection logic written and
then kept correct. Nothing here needs the client to talk back — dispositions
go over the ordinary API.

`events` is supplied by whoever wires the app factory, so the stream has no
opinion about where its events come from: a live meeting, or a replay.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

# Yields (event_name, payload) pairs for one meeting until the session ends.
SessionEvents = Callable[[str], AsyncIterator[tuple[str, dict[str, Any]]]]


def format_sse(event: str, payload: dict[str, Any]) -> str:
    """One SSE frame.

    The trailing blank line is what terminates a frame; without it the client
    buffers indefinitely and the panel simply never updates, which is a
    miserable thing to debug from the UI end.
    """

    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def build_session_stream_router(events: SessionEvents) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["live-session"])

    @router.get("/{meeting_id}/session/stream")
    async def stream_session(meeting_id: str) -> StreamingResponse:
        """Stream coverage and nudges for one meeting."""

        async def body() -> AsyncIterator[str]:
            async for name, payload in events(meeting_id):
                yield format_sse(name, payload)

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={
                # A proxy that buffers this defeats the point: the panel would
                # receive a meeting's worth of nudges at the end of it.
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router
