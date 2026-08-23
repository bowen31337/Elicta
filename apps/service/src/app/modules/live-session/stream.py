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

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

# Yields (event_name, payload) pairs for one meeting until the session ends.
SessionEvents = Callable[[str], AsyncIterator[tuple[str, dict[str, Any]]]]

#: How often the open connection says something when the meeting is quiet.
#: Chosen under the shortest idle timeout that tends to sit in front of this
#: (nginx's `proxy_read_timeout` defaults to 60s), so a silent meeting is not
#: mistaken for a dead connection by something in the middle.
HEARTBEAT_SECONDS = 15.0

#: How long one connection is held before it is closed and the client opens
#: another. Bounded rather than endless on purpose: a connection that never
#: ends cannot be recycled by anything in front of it, and cannot be read to
#: completion by a test. Five minutes is twelve reconnections in an hour-long
#: meeting, against the twelve hundred that draining and closing produced.
HOLD_SECONDS = 300.0

#: Names the window, because the right value is a property of whatever sits in
#: front of this rather than of this code: a deployment behind something that
#: culls connections at sixty seconds wants a window under sixty seconds.
HOLD_SECONDS_ENV = "ELICTA_SESSION_STREAM_HOLD_SECONDS"


def hold_seconds_from_env() -> float:
    """The configured hold window, or the default.

    A value that cannot be read as a positive number falls back rather than
    raising. Refusing to start the whole service over a malformed tuning knob
    would trade a slightly-wrong reconnection interval for no service at all.
    """

    raw = os.environ.get(HOLD_SECONDS_ENV, "").strip()
    if not raw:
        return HOLD_SECONDS
    try:
        configured = float(raw)
    except ValueError:
        return HOLD_SECONDS
    return configured if configured > 0 else HOLD_SECONDS


def format_sse(event: str, payload: dict[str, Any]) -> str:
    """One SSE frame.

    The trailing blank line is what terminates a frame; without it the client
    buffers indefinitely and the panel simply never updates, which is a
    miserable thing to debug from the UI end.
    """

    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def format_comment(text: str) -> str:
    """One SSE comment frame — traffic that carries no event.

    A line beginning with a colon is ignored by `EventSource` but still counts
    as bytes to everything between here and it, which is what keeps an idle
    connection from being reaped as dead.
    """

    return f": {text}\n\n"


def build_session_stream_router(
    events: SessionEvents,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    hold_seconds: float | None = None,
) -> APIRouter:
    # Resolved per build rather than baked into the signature default, so the
    # environment is read when the app is assembled and not when this module
    # is first imported.
    hold = hold_seconds_from_env() if hold_seconds is None else hold_seconds
    router = APIRouter(prefix="/api/meetings", tags=["live-session"])

    @router.get("/{meeting_id}/session/stream")
    async def stream_session(meeting_id: str) -> StreamingResponse:
        """Stream coverage and nudges for one meeting."""

        async def body() -> AsyncIterator[str]:
            async for name, payload in events(meeting_id):
                yield format_sse(name, payload)

            # Draining the backlog is not the end of the meeting, and
            # closing here was read by the panel as a dropped connection:
            # `EventSource` reconnects on its own timer (~3s), so the one
            # subscription became a poll of some twelve hundred connections an
            # hour, each re-sending the lane and language frames the panel
            # already had. The connection is held instead.
            #
            # Held, not endless. Two things want an end: anything in front of
            # this recycles connections on its own schedule and is happier
            # given one, and an endless body cannot be read to completion at
            # all — by a proxy, a diagnostic, or a test. So the connection
            # closes on a schedule the client already knows how to handle,
            # which makes the reconnection one every few minutes rather than
            # one every three seconds.
            #
            # The first comment goes out immediately rather than after a wait:
            # it is the only mark a reader gets for "that is all there is for
            # now", and without it the backlog has no observable end short of
            # closing the response, which is the thing being fixed.
            held = 0.0
            while True:
                yield format_comment("keep-alive")
                if held >= hold:
                    return
                # The last wait is trimmed to what is left of the window, and
                # counted as what was actually waited: adding a whole heartbeat
                # for a part-heartbeat sleep would close the connection early
                # and make the window mean something other than it says.
                waited = min(heartbeat_seconds, hold - held)
                await asyncio.sleep(waited)
                held += waited

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
