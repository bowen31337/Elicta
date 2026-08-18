"""HTTP surface for recording an operator's disposition of a surfaced nudge (PRD FR-6.6/6.7).

`build_nudge_disposition_router` takes a `record_disposition` callback
rather than importing a live-mode nudge store directly, mirroring every
other router in this codebase (`engagement/api/router.py`,
`live-session/router.py`): no persistence layer for nudges lives in this
package. Whoever wires the app factory (out of this feature's footprint)
supplies the real implementation and mounts the returned router.
`record_disposition` returns `None` when `meeting_id`/`nudge_id` don't
resolve to a nudge that can be dispositioned, which the route turns into a
404 rather than a 200 confirming something that was never recorded --
mirroring `build_meeting_router`'s handling of an unknown meeting.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import NudgeDispositionRequest, NudgeDispositionResponse

RecordDisposition = Callable[
    [str, str, NudgeDispositionRequest], Awaitable[NudgeDispositionResponse | None]
]


def build_nudge_disposition_router(record_disposition: RecordDisposition) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["nudges"])

    @router.post(
        "/{meeting_id}/nudges/{nudge_id}/disposition",
        response_model=NudgeDispositionResponse,
        status_code=200,
    )
    async def record_nudge_disposition_endpoint(
        meeting_id: str,
        nudge_id: str,
        payload: NudgeDispositionRequest,
    ) -> NudgeDispositionResponse:
        recorded = await record_disposition(meeting_id, nudge_id, payload)
        if recorded is None:
            raise HTTPException(status_code=404, detail="nudge not found")
        return recorded

    return router
