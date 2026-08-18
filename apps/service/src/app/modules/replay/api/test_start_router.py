from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.replay.api.errors import RecordingNotFoundError
from app.modules.replay.api.models import StartReplayRunRequest
from app.modules.replay.api.router import build_replay_start_router


def make_client(
    response: str | Exception = "run-1",
) -> tuple[TestClient, list[StartReplayRunRequest]]:
    received: list[StartReplayRunRequest] = []

    async def start_run(payload: StartReplayRunRequest) -> str:
        received.append(payload)
        if isinstance(response, Exception):
            raise response
        return response

    app = FastAPI()
    app.include_router(build_replay_start_router(start_run))
    return TestClient(app), received


def test_starting_a_run_returns_202_with_run_id():
    client, _ = make_client(response="run-123")

    response = client.post(
        "/api/replay/runs",
        json={"recording_id": "rec-1"},
    )

    assert response.status_code == 202
    assert response.json() == {"run_id": "run-123"}


def test_starting_a_run_passes_recording_id_through():
    client, received = make_client()

    client.post(
        "/api/replay/runs",
        json={"recording_id": "rec-42"},
    )

    assert len(received) == 1
    assert received[0].recording_id == "rec-42"


def test_missing_recording_id_is_rejected():
    client, _ = make_client()

    response = client.post("/api/replay/runs", json={})

    assert response.status_code == 422


def test_blank_recording_id_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/replay/runs",
        json={"recording_id": ""},
    )

    assert response.status_code == 422


def test_unknown_recording_id_returns_404():
    client, _ = make_client(response=RecordingNotFoundError("rec-missing"))

    response = client.post(
        "/api/replay/runs",
        json={"recording_id": "rec-missing"},
    )

    assert response.status_code == 404
