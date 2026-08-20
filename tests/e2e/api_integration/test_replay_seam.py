"""A replay run can be read back, and its ratings reach its metrics.

Two seams, the same shape twice: `start` wrote `backend.replay_run_requests`
while `status` read `backend.replay_statuses`, and ratings wrote
`backend.replay_ratings` while metrics read `backend.run_ratings`. A run
started over the API answered "no replay run" when asked about, and a rating
accepted with a `rating-1` id moved no number anywhere.

The old suite asserted `len(backend.replay_ratings) == 1` — the field the
write goes to — which is exactly why it never noticed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _start_run(client: TestClient, **extra: object) -> str:
    response = client.post(
        "/api/replay/runs", json={"recording_id": "recording-7", **extra}
    )
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def _rate(client: TestClient, run_id: str, suggestion_id: str, verdict: str) -> None:
    response = client.post(
        f"/api/replay/runs/{run_id}/ratings",
        json={"suggestion_id": suggestion_id, "verdict": verdict},
    )
    assert response.status_code == 201, response.text


def test_a_started_run_can_be_read_back(client: TestClient) -> None:
    run_id = _start_run(client)

    response = client.get(f"/api/replay/runs/{run_id}")

    assert response.status_code == 200, response.text
    status = response.json()
    assert status["run_id"] == run_id
    # Nothing executes a replay run in this deployment, so it is pending with
    # no suggestions. Reporting it as completed would be the lie.
    assert status["status"] == "pending"
    assert status["progress"] == 0.0
    assert status["suggestion_count"] == 0


def test_a_run_that_was_never_started_is_still_not_found(client: TestClient) -> None:
    response = client.get("/api/replay/runs/run-404")

    assert response.status_code == 404
    assert "run-404" in response.json()["detail"]


def test_a_submitted_rating_reaches_the_runs_metrics(client: TestClient) -> None:
    run_id = _start_run(client, language="en")

    _rate(client, run_id, "sugg-1", "useful")
    _rate(client, run_id, "sugg-2", "embarrassing")

    response = client.get(f"/api/replay/runs/{run_id}/metrics")
    assert response.status_code == 200, response.text
    metrics = response.json()
    assert metrics["run_id"] == run_id
    assert len(metrics["languages"]) == 1, metrics
    figure = metrics["languages"][0]
    assert figure["language"] == "en"
    assert figure["surfaced_count"] == 2
    assert figure["useful_count"] == 1
    assert figure["precision_at_surfaced"] == 0.5


def test_ratings_are_scored_under_their_own_runs_language(client: TestClient) -> None:
    """M1 is partitioned by the language of the run a rating belongs to (T13)."""

    english = _start_run(client, language="en")
    portuguese = _start_run(client, language="pt")

    _rate(client, english, "sugg-1", "useful")
    _rate(client, portuguese, "sugg-1", "useful")
    _rate(client, portuguese, "sugg-2", "embarrassing")

    figures = client.get(f"/api/replay/runs/{portuguese}/metrics").json()["languages"]
    assert [f["language"] for f in figures] == ["pt"]
    assert figures[0]["surfaced_count"] == 2, "another run's ratings leaked in"


def test_ratings_do_not_leak_between_runs(client: TestClient) -> None:
    first = _start_run(client)
    second = _start_run(client)

    _rate(client, first, "sugg-1", "useful")

    assert client.get(f"/api/replay/runs/{second}/metrics").json()["languages"] == []


def test_rating_a_run_that_does_not_exist_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/replay/runs/run-404/ratings",
        json={"suggestion_id": "sugg-1", "verdict": "useful"},
    )

    assert response.status_code == 404, response.text
