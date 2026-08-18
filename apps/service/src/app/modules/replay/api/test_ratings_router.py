from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.replay.api.models import SuggestionRatingRequest
from app.modules.replay.api.router import build_replay_ratings_router


def make_client(
    rating_id: str = "r1",
) -> tuple[TestClient, list[tuple[str, SuggestionRatingRequest]]]:
    received: list[tuple[str, SuggestionRatingRequest]] = []

    async def save_rating(run_id: str, payload: SuggestionRatingRequest) -> str:
        received.append((run_id, payload))
        return rating_id

    app = FastAPI()
    app.include_router(build_replay_ratings_router(save_rating))
    return TestClient(app), received


def test_rating_a_suggestion_returns_201_with_rating_id():
    client, _ = make_client(rating_id="rating-123")

    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "useful"},
    )

    assert response.status_code == 201
    assert response.json() == {"rating_id": "rating-123"}


def test_rating_passes_run_id_and_payload_through():
    client, received = make_client()

    client.post(
        "/api/replay/runs/run-42/ratings",
        json={"suggestion_id": "sugg-9", "verdict": "timely"},
    )

    assert len(received) == 1
    run_id, payload = received[0]
    assert run_id == "run-42"
    assert payload.suggestion_id == "sugg-9"
    assert payload.verdict == "timely"


def test_embarrassing_verdict_is_accepted():
    client, received = make_client()

    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "embarrassing"},
    )

    assert response.status_code == 201
    assert received[0][1].verdict == "embarrassing"


def test_unknown_verdict_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "hilarious"},
    )

    assert response.status_code == 422


def test_missing_suggestion_id_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"verdict": "useful"},
    )

    assert response.status_code == 422


def test_blank_suggestion_id_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "", "verdict": "useful"},
    )

    assert response.status_code == 422
