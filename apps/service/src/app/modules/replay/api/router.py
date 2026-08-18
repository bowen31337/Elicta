"""HTTP surface for rating a replay run's suggestions (feature 26).

`build_replay_ratings_router` takes a `save_rating` callback rather than
importing a ratings persistence model directly, since that layer does not
live in this package (`app/modules/replay/api`). Whoever wires the app
factory (out of this feature's footprint) supplies the real,
persistence-backed implementation and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from app.modules.replay.api.models import (
    SuggestionRatingRequest,
    SuggestionRatingResponse,
)

SaveSuggestionRating = Callable[[str, SuggestionRatingRequest], Awaitable[str]]


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
        rating_id = await save_rating(run_id, payload)
        return SuggestionRatingResponse(rating_id=rating_id)

    return router
