"""`POST /api/meetings/{id}/live/utterance` — the seam finalised text lands on.

Named for what it carries rather than for what produces it. Whatever turns
speech into text -- a streaming vendor called by this service, a recogniser in
the client, a harness replaying a transcript -- hands utterances over here, and
the gate behind it neither knows nor cares which.

Takes its behaviour as a callable, like every other router in this service.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import UtteranceAccepted, UtteranceRequest

ObserveUtterance = Callable[[str, UtteranceRequest], Awaitable[UtteranceAccepted | None]]


def build_live_utterance_router(observe: ObserveUtterance) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["live-lane"])

    @router.post(
        "/{meeting_id}/live/utterance",
        response_model=UtteranceAccepted,
        status_code=202,
    )
    async def observe_utterance(meeting_id: str, payload: UtteranceRequest) -> UtteranceAccepted:
        """Evaluate one utterance, and surface a question if it earns one.

        202 rather than 201: nothing durable is created here. A nudge lives
        for the meeting it was raised in, and what outlives it is the
        operator's disposition of it, recorded on its own route.
        """

        observed = await observe(meeting_id, payload)
        if observed is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return observed

    return router
