"""Happy-path 2xx and documented-4xx coverage for the replay ratings/status API."""

from __future__ import annotations

from app.modules.replay.api.models import ReplayRunStatus, ReplayRunStatusResponse
from fastapi.testclient import TestClient

from conftest import Backend


def test_rate_suggestion_returns_201(client: TestClient) -> None:
    """Rate a run that was started through the API, and read the rating back through it.

    This used to rate `run-1` — a run nothing had started — and then assert
    `len(backend.replay_ratings) == 1`, the field the write goes to. Both
    halves passed while the seam between the write and the metrics endpoint
    was not connected at all; `run_ratings` is what metrics reads.
    """

    started = client.post("/api/replay/runs", json={"recording_id": "recording-1"})
    run_id = started.json()["run_id"]

    response = client.post(
        f"/api/replay/runs/{run_id}/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "useful"},
    )

    assert response.status_code == 201
    assert response.json()["rating_id"]

    metrics = client.get(f"/api/replay/runs/{run_id}/metrics").json()
    assert metrics["languages"][0]["useful_count"] == 1


def test_rate_suggestion_blank_suggestion_id_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "", "verdict": "useful"},
    )

    assert response.status_code == 422


def test_rate_suggestion_invalid_verdict_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/replay/runs/run-1/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "not-a-real-verdict"},
    )

    assert response.status_code == 422


def test_get_run_status_returns_200(client: TestClient, backend: Backend) -> None:
    backend.replay_statuses["run-1"] = ReplayRunStatusResponse(
        run_id="run-1", status=ReplayRunStatus.RUNNING, progress=0.5, suggestion_count=3
    )

    response = client.get("/api/replay/runs/run-1")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_get_run_status_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/replay/runs/unknown")

    assert response.status_code == 404
