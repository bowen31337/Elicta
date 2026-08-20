"""The app can discover which engagement, meeting or replay run to show.

The six unwired desktop screens (US-010) each need an id before they can ask
the service anything, and until now the API offered no way to obtain one: a
POST handed back an id exactly once, and nothing listed them afterwards. An
operator who restarted the app had no route back to their own engagement,
which is why `debrief-chat` shipped with the literal `'meeting-1'` in it.

Three reads close that: `GET /api/engagements`, `GET
/api/engagements/{id}/meetings` and `GET /api/replay/runs`. As everywhere in
this suite, every fixture below is built through the API — nothing assigns to
a `backend.*` field to set up a read.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_engagement(client: TestClient, organisation: str) -> str:
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": organisation,
            "sector": "logistics",
            "commercial_context": "Discovery engagement for a depot scheduling rebuild",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["engagement_id"]


def _create_meeting(client: TestClient, engagement_id: str, capture_mode: str = "live") -> str:
    response = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": capture_mode},
    )
    assert response.status_code == 201, response.text
    return response.json()["meeting_id"]


def test_a_created_engagement_appears_in_the_engagement_list(client: TestClient) -> None:
    engagement_id = _create_engagement(client, "Northwind Freight")

    response = client.get("/api/engagements")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert [item["engagement_id"] for item in body["items"]] == [engagement_id]
    assert body["items"][0]["client_organisation"] == "Northwind Freight"


def test_the_engagement_list_is_empty_rather_than_absent(client: TestClient) -> None:
    response = client.get("/api/engagements")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_a_created_engagement_can_be_read_back_by_id(client: TestClient) -> None:
    engagement_id = _create_engagement(client, "Northwind Freight")

    response = client.get(f"/api/engagements/{engagement_id}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["client_organisation"] == "Northwind Freight"
    assert detail["document_count"] == 0


def test_an_unknown_engagement_is_a_404_not_an_empty_body(client: TestClient) -> None:
    assert client.get("/api/engagements/eng-nope").status_code == 404


def test_created_meetings_are_listed_under_their_engagement(client: TestClient) -> None:
    engagement_id = _create_engagement(client, "Northwind Freight")
    other_id = _create_engagement(client, "Southbank Utilities")
    first = _create_meeting(client, engagement_id)
    second = _create_meeting(client, engagement_id, capture_mode="record")
    elsewhere = _create_meeting(client, other_id)

    response = client.get(f"/api/engagements/{engagement_id}/meetings")

    assert response.status_code == 200, response.text
    listed = response.json()["meetings"]
    assert [meeting["meeting_id"] for meeting in listed] == [first, second]
    assert elsewhere not in [meeting["meeting_id"] for meeting in listed]
    assert listed[1]["capture_mode"] == "record"


def test_a_meeting_list_carries_the_session_purpose_once_it_is_set(client: TestClient) -> None:
    engagement_id = _create_engagement(client, "Northwind Freight")
    meeting_id = _create_meeting(client, engagement_id)
    patched = client.patch(
        f"/api/meetings/{meeting_id}",
        json={"session_purpose": "Depot scheduling discovery"},
    )
    assert patched.status_code == 200, patched.text

    response = client.get(f"/api/engagements/{engagement_id}/meetings")

    assert response.status_code == 200, response.text
    assert response.json()["meetings"][0]["session_purpose"] == "Depot scheduling discovery"


def test_an_engagement_with_no_meetings_lists_none(client: TestClient) -> None:
    engagement_id = _create_engagement(client, "Northwind Freight")

    response = client.get(f"/api/engagements/{engagement_id}/meetings")

    assert response.status_code == 200, response.text
    assert response.json()["meetings"] == []


def test_meetings_for_an_unknown_engagement_are_a_404(client: TestClient) -> None:
    assert client.get("/api/engagements/eng-nope/meetings").status_code == 404


def test_a_started_replay_run_appears_in_the_run_list(client: TestClient) -> None:
    started = client.post(
        "/api/replay/runs",
        json={"recording_id": "rec-1", "language": "en"},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    response = client.get("/api/replay/runs")

    assert response.status_code == 200, response.text
    runs = response.json()["runs"]
    assert [run["run_id"] for run in runs] == [run_id]
    assert runs[0]["recording_id"] == "rec-1"
    assert runs[0]["language"] == "en"


def test_the_replay_run_list_is_empty_rather_than_absent(client: TestClient) -> None:
    response = client.get("/api/replay/runs")

    assert response.status_code == 200, response.text
    assert response.json()["runs"] == []
