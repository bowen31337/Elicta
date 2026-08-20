"""HTTP surface for starting replay runs and their ratings and status.

Each `build_*_router` takes a callback rather than importing a persistence
model directly, since that layer does not live in this package
(`app/modules/replay/api`). Whoever wires the app factory (out of this
feature's footprint) supplies the real, persistence-backed implementation
and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from app.modules.replay.api.errors import (
    RecordingNotFoundError,
    ReplayRunNotFoundError,
)
from app.modules.replay.api.models import (
    ReplayRunListResponse,
    ReplayRunStatusResponse,
    ReplayRunSummary,
    StartReplayRunRequest,
    StartReplayRunResponse,
    SuggestionRatingRequest,
    SuggestionRatingResponse,
)

SaveSuggestionRating = Callable[[str, SuggestionRatingRequest], Awaitable[str]]
GetReplayRunStatus = Callable[[str], Awaitable[ReplayRunStatusResponse]]
StartReplayRun = Callable[[StartReplayRunRequest], Awaitable[str]]
ListReplayRuns = Callable[[], Awaitable[list[ReplayRunSummary]]]


def build_replay_start_router(start_run: StartReplayRun) -> APIRouter:
    router = APIRouter(prefix="/api/replay/runs", tags=["replay-runs"])

    @router.post(
        "",
        response_model=StartReplayRunResponse,
        status_code=202,
    )
    async def start_replay_run(
        payload: StartReplayRunRequest,
    ) -> StartReplayRunResponse:
        try:
            run_id = await start_run(payload)
        except RecordingNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StartReplayRunResponse(run_id=run_id)

    return router


def build_replay_ratings_router(save_rating: SaveSuggestionRating) -> APIRouter:
    router = APIRouter(prefix="/api/replay/runs", tags=["replay-ratings"])

    @router.post(
        "/{run_id}/ratings",
        response_model=SuggestionRatingResponse,
        status_code=201,
    )
    async def rate_suggestion(
        run_id: str, payload: SuggestionRatingRequest
    ) -> SuggestionRatingResponse:
        try:
            rating_id = await save_rating(run_id, payload)
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return SuggestionRatingResponse(rating_id=rating_id)

    return router


def build_replay_status_router(get_status: GetReplayRunStatus) -> APIRouter:
    router = APIRouter(prefix="/api/replay/runs", tags=["replay-status"])

    @router.get(
        "/{run_id}",
        response_model=ReplayRunStatusResponse,
        status_code=200,
    )
    async def get_run_status(run_id: str) -> ReplayRunStatusResponse:
        try:
            return await get_status(run_id)
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def build_replay_run_list_router(list_runs: ListReplayRuns) -> APIRouter:
    """Build the replay run list route.

    `POST /api/replay/runs` handed back a run id exactly once and nothing
    listed them afterwards, so the replay screen had no way to name a run it
    had not just started. This is that read. It is registered on its own
    router, mounted before the status router, so that `""` and `/{run_id}`
    stay unambiguous paths rather than one shadowing the other.

    An empty list is a 200: a service that has replayed nothing yet is a
    normal state.
    """

    router = APIRouter(prefix="/api/replay/runs", tags=["replay-runs"])

    @router.get(
        "",
        response_model=ReplayRunListResponse,
        status_code=200,
    )
    async def list_replay_runs() -> ReplayRunListResponse:
        return ReplayRunListResponse(runs=await list_runs())

    return router
