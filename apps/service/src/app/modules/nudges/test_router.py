"""Tests for recording an operator's disposition of a surfaced nudge (PRD FR-6.6/6.7).

Covers `POST /api/meetings/{meeting_id}/nudges/{nudge_id}/disposition`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.nudges.models import NudgeDispositionRequest, NudgeDispositionResponse
from app.modules.nudges.router import build_nudge_disposition_router


def make_client(
    known_nudges: set[tuple[str, str]] | None = None,
) -> tuple[TestClient, list[tuple[str, str, NudgeDispositionRequest]]]:
    known = known_nudges if known_nudges is not None else {("meeting-1", "nudge-1")}
    received: list[tuple[str, str, NudgeDispositionRequest]] = []

    async def record_disposition(meeting_id: str, nudge_id: str, payload: NudgeDispositionRequest):
        received.append((meeting_id, nudge_id, payload))
        if (meeting_id, nudge_id) not in known:
            return None
        return NudgeDispositionResponse(
            meeting_id=meeting_id,
            nudge_id=nudge_id,
            disposition=payload.disposition,
            recorded_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        )

    app = FastAPI()
    app.include_router(build_nudge_disposition_router(record_disposition))
    return TestClient(app), received


def test_recording_a_disposition_returns_200_with_the_recorded_disposition():
    client, _ = make_client(known_nudges={("meeting-1", "nudge-1")})

    response = client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={"disposition": "taken"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert body["nudge_id"] == "nudge-1"
    assert body["disposition"] == "taken"
    assert body["recorded_at"] == "2026-08-19T09:00:00Z"


def test_recording_a_disposition_passes_the_path_ids_and_payload_through():
    client, received = make_client(known_nudges={("meeting-1", "nudge-1")})

    client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={"disposition": "parked"},
    )

    assert len(received) == 1
    meeting_id, nudge_id, payload = received[0]
    assert meeting_id == "meeting-1"
    assert nudge_id == "nudge-1"
    assert payload.disposition == "parked"


def test_parked_is_a_valid_disposition():
    client, _ = make_client(known_nudges={("meeting-1", "nudge-1")})

    response = client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={"disposition": "parked"},
    )

    assert response.status_code == 200
    assert response.json()["disposition"] == "parked"


def test_recording_a_disposition_for_an_unknown_nudge_returns_404():
    client, _ = make_client(known_nudges=set())

    response = client.post(
        "/api/meetings/meeting-1/nudges/does-not-exist/disposition",
        json={"disposition": "taken"},
    )

    assert response.status_code == 404


def test_fired_is_not_a_valid_operator_disposition():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={"disposition": "fired"},
    )

    assert response.status_code == 422


def test_missing_disposition_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={},
    )

    assert response.status_code == 422


def test_an_unknown_field_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/nudges/nudge-1/disposition",
        json={"disposition": "taken", "notes": "should not be accepted"},
    )

    assert response.status_code == 422
