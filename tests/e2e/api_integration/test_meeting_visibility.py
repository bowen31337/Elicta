"""A meeting created through the API is visible to every route that takes a meeting id.

The defect this covers: `create_meeting` wrote only `backend.meeting_engagement_ids`,
while `GET /api/meetings/{id}` read `backend.meeting_details` and `session/start`,
`session/stream` and `slow-lane/tick` all gated on `backend.known_meetings` — a field
nothing in production code ever wrote. Every meeting created over the real API
therefore 404'd at the very next call, so the operator panel could never receive a
stream from a running service.

Every fixture here is built with API calls. Nothing assigns to a `backend.*` field to
set up a read — that is precisely the habit that let the seam stay broken while 45
integration tests passed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_engagement(client: TestClient) -> str:
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Freight",
            "sector": "logistics",
            "commercial_context": "Discovery engagement for a depot scheduling rebuild",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["engagement_id"]


def _create_meeting(client: TestClient, engagement_id: str) -> str:
    response = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "live"},
    )
    assert response.status_code == 201, response.text
    return response.json()["meeting_id"]


def test_created_meeting_can_be_read_back_by_id(client: TestClient) -> None:
    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)

    response = client.get(f"/api/meetings/{meeting_id}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["meeting_id"] == meeting_id
    assert detail["engagement_id"] == engagement_id
    assert detail["capture_mode"] == "live"


def test_created_meeting_is_known_to_the_live_session_routes(client: TestClient) -> None:
    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)
    # Capture is gated on consent (PRD L1/L2, D3), which is its own seam and
    # its own test — confirmed here so that what this test measures is
    # whether the meeting is *known*, not whether the gate is open.
    client.post(
        f"/api/meetings/{meeting_id}/consent-confirmation",
        json={"confirmed_by": "Priya Raman"},
    )

    started = client.post(f"/api/meetings/{meeting_id}/session/start")
    assert started.status_code != 404, "the meeting the API just issued is not found"
    assert started.status_code == 200, started.text
    assert started.json()["meeting_id"] == meeting_id

    ticked = client.post(f"/api/meetings/{meeting_id}/slow-lane/tick")
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["meeting_id"] == meeting_id

    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as stream:
        assert stream.status_code == 200
        body = b"".join(stream.iter_bytes()).decode()
    assert "lane" in body


def test_a_meeting_id_that_was_never_issued_is_still_not_found(client: TestClient) -> None:
    """The guard must stay a guard — fixing the write side must not open it to anything."""

    assert client.get("/api/meetings/meeting-404").status_code == 404
    # 404, not the 403 an unconfirmed meeting gets: a meeting that was never
    # issued does not exist, which is a different answer from "not yet".
    assert client.post("/api/meetings/meeting-404/session/start").status_code == 404
    assert client.post("/api/meetings/meeting-404/slow-lane/tick").status_code == 404
