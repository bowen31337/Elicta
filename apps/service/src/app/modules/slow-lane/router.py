"""HTTP surface for accepting a slow-lane tick for a meeting (PRD FR-5.10; architecture §3.8).

`build_slow_lane_tick_router` takes a `run_tick` callback rather than
importing a concrete Messages-API-calling pass implementation, mirroring
every other router in this codebase (`nudges/router.py`,
`app/modules/live-session/router.py`): assembling the partitioned prompt,
calling the Messages API, and writing results back into the bank (PRD
FR-5.10, architecture §3.8) are separate concerns this package only exposes
over HTTP. Whoever wires the app factory (out of this feature's footprint)
supplies the real implementation -- draining `core/crates/slow-lane`'s
`TickEvent`s, running the pass, and reporting what it produced -- and mounts
the returned router.

`run_tick` returns `None` when `meeting_id` does not resolve to a meeting,
which this route turns into a 404 rather than fabricating a tick result for
a meeting that doesn't exist -- the same convention
`build_live_session_router` uses for an unknown meeting.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import SlowLaneTickResult

RunSlowLaneTick = Callable[[str], Awaitable[SlowLaneTickResult | None]]


def build_slow_lane_tick_router(run_tick: RunSlowLaneTick) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["slow-lane"])

    @router.post(
        "/{meeting_id}/slow-lane/tick",
        response_model=SlowLaneTickResult,
        status_code=200,
    )
    async def accept_slow_lane_tick(meeting_id: str) -> SlowLaneTickResult:
        result = await run_tick(meeting_id)
        if result is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return result

    return router
