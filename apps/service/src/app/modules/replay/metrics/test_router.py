from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.replay.api.errors import ReplayRunNotFoundError

from .models import RatedSuggestion
from .router import build_replay_metrics_router


def rating(
    language: str, *, useful: bool = False, embarrassing: bool = False
) -> RatedSuggestion:
    return RatedSuggestion(language=language, useful=useful, embarrassing=embarrassing)


def make_client(
    ratings: Iterable[RatedSuggestion] | Exception,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def get_ratings(run_id: str) -> Iterable[RatedSuggestion]:
        received.append(run_id)
        if isinstance(ratings, Exception):
            raise ratings
        return ratings

    app = FastAPI()
    app.include_router(build_replay_metrics_router(get_ratings))
    return TestClient(app), received


def test_getting_run_metrics_returns_200_with_precision_at_surfaced():
    client, _ = make_client(
        [
            rating("en", useful=True),
            rating("en", useful=True),
            rating("en", useful=False),
            rating("en", useful=False),
        ]
    )

    response = client.get("/api/replay/runs/run-1/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "languages": [
            {
                "language": "en",
                "surfaced_count": 4,
                "useful_count": 2,
                "precision_at_surfaced": 0.5,
            }
        ],
    }


def test_getting_run_metrics_passes_run_id_through():
    client, received = make_client([rating("en", useful=True)])

    client.get("/api/replay/runs/run-42/metrics")

    assert received == ["run-42"]


def test_run_with_no_ratings_returns_no_languages():
    client, _ = make_client([])

    response = client.get("/api/replay/runs/run-1/metrics")

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-1", "languages": []}


def test_ratings_are_broken_out_per_language_never_blended():
    client, _ = make_client(
        [
            rating("en", useful=True),
            rating("en", useful=False),
            rating("vi", useful=True),
            rating("vi", useful=True),
        ]
    )

    response = client.get("/api/replay/runs/run-1/metrics")

    languages = {entry["language"]: entry for entry in response.json()["languages"]}
    assert languages["en"]["precision_at_surfaced"] == 0.5
    assert languages["vi"]["precision_at_surfaced"] == 1.0


def test_unknown_run_id_returns_404():
    client, _ = make_client(ReplayRunNotFoundError("run-missing"))

    response = client.get("/api/replay/runs/run-missing/metrics")

    assert response.status_code == 404
