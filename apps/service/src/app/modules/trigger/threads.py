"""What an operator does with a surfaced question, beyond asking it.

Two of the panel's four one-tap responses need the service to know which
thread is meant, and both addressed `/api/threads/{id}/...` for months against
a service that served neither — so `Park it` and `Go deeper` answered 404 on
every tap. The panel reported the failure and carried on, which is right for a
panel mid-meeting and meant nobody found out from the screen.

A thread is a surfaced nudge. The id in the URL is the id the stream carried,
which is why nothing is sent in the body: the service already holds what was
asked and what fired it.

Takes both behaviours as callables, like every other router here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import FollowOnQuestion, ParkedThread

ParkThread = Callable[[str], Awaitable[ParkedThread | None]]
DeepenThread = Callable[[str], Awaitable[FollowOnQuestion | None]]


def build_thread_router(park: ParkThread, deepen: DeepenThread) -> APIRouter:
    router = APIRouter(prefix="/api/threads", tags=["nudges"])

    @router.post("/{thread_id}/park", response_model=ParkedThread, status_code=200)
    async def park_thread(thread_id: str) -> ParkedThread:
        """Defer this question to the debrief rather than dropping it."""

        parked = await park(thread_id)
        if parked is None:
            raise HTTPException(status_code=404, detail="no such thread")
        return parked

    @router.post("/{thread_id}/go-deeper", response_model=FollowOnQuestion, status_code=200)
    async def deepen_thread(thread_id: str) -> FollowOnQuestion:
        """The next question on the same thread — never the one already asked."""

        deeper = await deepen(thread_id)
        if deeper is None:
            raise HTTPException(status_code=404, detail="no such thread")
        return deeper

    return router
