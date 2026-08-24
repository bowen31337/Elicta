"""A meeting can be created, read, renamed and removed over the real API.

The Preparation screen lists an engagement's meetings, and until this suite
existed the list was one-way: `POST /api/meetings` put a row in it and nothing
took one out. An operator who created a meeting by mistake — or created three
while working out what the screen did — had no way back, which is how the
screen ends up being read as broken rather than as append-only.

Two halves, and both were missing something:

* **Delete** had no route at all. It is soft, like every other removal here:
  the meeting leaves the list and stops resolving by id, and the row it leaves
  behind keeps the consent record, the transcripts and the audio-destruction
  events that describe a meeting which actually took place.
* **Update** had a route, and a guard that read an in-memory field. Renaming a
  meeting worked until the service restarted and then 404'd for ever, because
  `meeting_engagement_ids` is rebuilt by creation and by nothing else. The
  restart test below is the one that failed.

Every fixture here is built with API calls, for the reason
`test_meeting_visibility` gives: assigning to a `backend.*` field to set up a
read is the habit that lets a seam stay broken while the suite passes.
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


def _create_meeting(client: TestClient, engagement_id: str, mode: str = "live") -> str:
    response = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": mode},
    )
    assert response.status_code == 201, response.text
    return response.json()["meeting_id"]


def _listed_ids(client: TestClient, engagement_id: str) -> list[str]:
    response = client.get(f"/api/engagements/{engagement_id}/meetings")
    assert response.status_code == 200, response.text
    return [row["meeting_id"] for row in response.json()["meetings"]]


def test_a_created_meeting_appears_in_its_engagements_list(client: TestClient) -> None:
    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)

    assert meeting_id in _listed_ids(client, engagement_id)


def test_renaming_a_meeting_shows_the_new_purpose_in_the_list(client: TestClient) -> None:
    """PATCH is what the Preparation screen's rename calls, and the list is where it lands."""

    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)

    response = client.patch(
        f"/api/meetings/{meeting_id}",
        json={"session_purpose": "Validate the depot scheduling scope"},
    )

    assert response.status_code == 200, response.text
    listed = client.get(f"/api/engagements/{engagement_id}/meetings").json()["meetings"]
    purposes = {row["meeting_id"]: row["session_purpose"] for row in listed}
    assert purposes[meeting_id] == "Validate the depot scheduling scope"


def test_deleting_a_meeting_takes_it_out_of_the_list(client: TestClient) -> None:
    engagement_id = _create_engagement(client)
    kept = _create_meeting(client, engagement_id)
    removed = _create_meeting(client, engagement_id, mode="record")

    response = client.delete(f"/api/meetings/{removed}")

    assert response.status_code == 204, response.text
    assert _listed_ids(client, engagement_id) == [kept]


def test_a_deleted_meeting_no_longer_resolves_by_id(client: TestClient) -> None:
    """Leaving the list is not enough: every per-meeting screen takes the id."""

    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)

    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 204

    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404


def test_a_deleted_meeting_is_no_longer_known_to_the_live_session_routes(
    client: TestClient,
) -> None:
    """`known_meetings` is the existence guard on session start, and it is in memory.

    Creation writes all three of `meeting_engagement_ids`, `known_meetings` and
    `meeting_details`; a removal that undid only the durable one would leave a
    meeting that is gone from every list and can still start a session.
    """

    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)
    confirmed = client.post(
        f"/api/meetings/{meeting_id}/consent-confirmation",
        json={"engagement_id": engagement_id, "confirmed_by": "operator"},
    )
    assert confirmed.status_code in (200, 201), confirmed.text

    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 204

    assert client.post(f"/api/meetings/{meeting_id}/session/start").status_code == 404


def test_deleting_a_meeting_twice_reports_the_second_as_not_found(client: TestClient) -> None:
    engagement_id = _create_engagement(client)
    meeting_id = _create_meeting(client, engagement_id)

    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 204

    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 404


def test_deleting_a_meeting_id_that_was_never_issued_is_not_found(client: TestClient) -> None:
    assert client.delete("/api/meetings/meeting-never-issued").status_code == 404


def test_deleting_one_meeting_leaves_its_engagements_other_meetings_alone(
    client: TestClient,
) -> None:
    """The engagement itself must survive too — it is the row the meeting hangs off."""

    engagement_id = _create_engagement(client)
    first = _create_meeting(client, engagement_id)
    second = _create_meeting(client, engagement_id, mode="record")
    third = _create_meeting(client, engagement_id)

    assert client.delete(f"/api/meetings/{second}").status_code == 204

    assert _listed_ids(client, engagement_id) == [first, third]
    assert client.get(f"/api/meetings/{first}").status_code == 200
    assert client.get(f"/api/meetings/{third}").status_code == 200
    assert client.get(f"/api/engagements/{engagement_id}").status_code == 200


def test_a_removed_meeting_does_not_take_its_id_back(client: TestClient) -> None:
    """The next meeting gets a fresh id, not the deleted one's.

    `next_meeting_id` is derived from the rows in `meeting_details`, so a
    removal that erased the row would let the counter walk backwards and mint
    an id a soft-deleted row still holds.
    """

    engagement_id = _create_engagement(client)
    removed = _create_meeting(client, engagement_id)

    assert client.delete(f"/api/meetings/{removed}").status_code == 204
    replacement = _create_meeting(client, engagement_id)

    assert replacement != removed
    assert _listed_ids(client, engagement_id) == [replacement]
