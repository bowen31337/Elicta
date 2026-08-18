from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.replay.api.errors import ReplayRunNotFoundError
from app.modules.replay.api.models import ReplayRunStatus, ReplayRunStatusResponse
from app.modules.replay.api.router import build_replay_status_router


def make_client(
    response: ReplayRunStatusResponse | Exception,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def get_status(run_id: str) -> ReplayRunStatusResponse:
        received.append(run_id)
        if isinstance(response, Exception):
            raise response
        return response

    app = FastAPI()
    app.include_router(build_replay_status_router(get_status))
    return TestClient(app), received


def test_getting_run_status_returns_200_with_progress_and_suggestion_count():
    client, _ = make_client(
        ReplayRunStatusResponse(
            run_id="run-1",
            status=ReplayRunStatus.RUNNING,
            progress=0.5,
            suggestion_count=7,
        )
    )

    response = client.get("/api/replay/runs/run-1")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "status": "running",
        "progress": 0.5,
        "suggestion_count": 7,
    }


def test_getting_run_status_passes_run_id_through():
    client, received = make_client(
        ReplayRunStatusResponse(
            run_id="run-42",
            status=ReplayRunStatus.COMPLETED,
            progress=1.0,
            suggestion_count=12,
        )
    )

    client.get("/api/replay/runs/run-42")

    assert received == ["run-42"]


def test_pending_run_reports_zero_progress_and_suggestions():
    client, _ = make_client(
        ReplayRunStatusResponse(
            run_id="run-1",
            status=ReplayRunStatus.PENDING,
            progress=0.0,
            suggestion_count=0,
        )
    )

    response = client.get("/api/replay/runs/run-1")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["progress"] == 0.0
    assert response.json()["suggestion_count"] == 0


def test_failed_run_status_is_reported():
    client, _ = make_client(
        ReplayRunStatusResponse(
            run_id="run-1",
            status=ReplayRunStatus.FAILED,
            progress=0.3,
            suggestion_count=2,
        )
    )

    response = client.get("/api/replay/runs/run-1")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_unknown_run_id_returns_404():
    client, _ = make_client(ReplayRunNotFoundError("run-missing"))

    response = client.get("/api/replay/runs/run-missing")

    assert response.status_code == 404
