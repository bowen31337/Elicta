"""HTTP surface for a replay run's M1 (precision@surfaced) figures.

`build_replay_metrics_router` takes a callback rather than importing the
`replay_ratings` persistence model directly, since that table does not live
in this package (`app/modules/replay/metrics`) — same reasoning as
`app/modules/replay/api/router.py`. Whoever wires the app factory (out of
this feature's footprint) supplies the real, persistence-backed
implementation and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, HTTPException

from app.modules.replay.api.errors import ReplayRunNotFoundError

from .models import RatedSuggestion
from .schemas import LanguagePrecision, ReplayRunMetricsResponse
from .scoring import group_by_language, score_language

GetRunRatings = Callable[[str], Awaitable[Iterable[RatedSuggestion]]]


def build_replay_metrics_router(get_ratings: GetRunRatings) -> APIRouter:
    router = APIRouter(prefix="/api/replay/runs", tags=["replay-metrics"])

    @router.get(
        "/{run_id}/metrics",
        response_model=ReplayRunMetricsResponse,
        status_code=200,
    )
    async def get_run_metrics(run_id: str) -> ReplayRunMetricsResponse:
        try:
            ratings = await get_ratings(run_id)
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        languages = []
        for language, group in group_by_language(ratings).items():
            figure = score_language(language, group)
            languages.append(
                LanguagePrecision(
                    language=figure.language,
                    surfaced_count=figure.surfaced_count,
                    useful_count=figure.useful_count,
                    precision_at_surfaced=figure.precision_at_surfaced,
                    embarrassing_count=figure.embarrassing_count,
                    clears_m2_gate=figure.clears_m2_gate,
                )
            )

        return ReplayRunMetricsResponse(run_id=run_id, languages=languages)

    return router
