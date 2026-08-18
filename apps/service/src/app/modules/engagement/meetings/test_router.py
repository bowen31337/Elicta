"""Tests for the meeting attendees HTTP surface (PRD FR-3.9, FR-3.10)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.engagement.meetings.models import Attendee, AttendeeCreateRequest
from app.modules.engagement.meetings.router import build_meeting_attendees_router


def make_client() -> tuple[TestClient, list[tuple[str, AttendeeCreateRequest]]]:
    received: list[tuple[str, AttendeeCreateRequest]] = []

    async def add_attendee(meeting_id: str, payload: AttendeeCreateRequest) -> Attendee:
        received.append((meeting_id, payload))
        return Attendee(
            id=uuid.uuid4().hex,
            meeting_id=meeting_id,
            display_name=payload.display_name,
            role=payload.role,
            business_function=payload.business_function,
            decision_authority=payload.decision_authority,
            domain_expertise=payload.domain_expertise,
        )

    app = FastAPI()
    app.include_router(build_meeting_attendees_router(add_attendee))
    return TestClient(app), received


def test_adding_an_attendee_returns_201_with_the_persisted_attendee():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={
            "display_name": "Jamie Rivera",
            "role": "VP Operations",
            "business_function": "Operations",
            "decision_authority": "decision_maker",
            "domain_expertise": ["warehouse logistics", "capex approval"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["meeting_id"] == "meeting-1"
    assert body["display_name"] == "Jamie Rivera"
    assert body["role"] == "VP Operations"
    assert body["business_function"] == "Operations"
    assert body["decision_authority"] == "decision_maker"
    assert body["domain_expertise"] == ["warehouse logistics", "capex approval"]


def test_adding_an_attendee_passes_the_structured_fields_through():
    client, received = make_client()

    client.post(
        "/api/meetings/meeting-1/attendees",
        json={
            "display_name": "Jamie Rivera",
            "role": "VP Operations",
            "business_function": "Operations",
            "decision_authority": "decision_maker",
            "domain_expertise": ["warehouse logistics"],
        },
    )

    assert len(received) == 1
    meeting_id, payload = received[0]
    assert meeting_id == "meeting-1"
    assert payload.role == "VP Operations"
    assert payload.business_function == "Operations"
    assert payload.decision_authority == "decision_maker"
    assert payload.domain_expertise == ["warehouse logistics"]


def test_an_attendee_can_be_added_from_the_four_structured_fields_alone():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={
            "role": "VP Operations",
            "business_function": "Operations",
            "decision_authority": "decision_maker",
            "domain_expertise": ["warehouse logistics"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] is None
    assert body["role"] == "VP Operations"
    assert body["business_function"] == "Operations"
    assert body["decision_authority"] == "decision_maker"
    assert body["domain_expertise"] == ["warehouse logistics"]


def test_no_fields_are_required():
    client, _ = make_client()

    response = client.post("/api/meetings/meeting-1/attendees", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["role"] is None
    assert body["business_function"] is None
    assert body["decision_authority"] is None
    assert body["domain_expertise"] == []


def test_blank_display_name_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={"display_name": ""},
    )

    assert response.status_code == 422


def test_a_free_text_assessment_field_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={
            "display_name": "Jamie Rivera",
            "assessment": "Defensive, blocks everything",
        },
    )

    assert response.status_code == 422


def test_domain_expertise_supports_more_than_one_area():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={
            "display_name": "Jamie Rivera",
            "domain_expertise": [
                "warehouse logistics",
                "capex approval",
                "procurement",
            ],
        },
    )

    assert response.json()["domain_expertise"] == [
        "warehouse logistics",
        "capex approval",
        "procurement",
    ]


def test_each_invitee_on_a_calendar_invite_persists_as_an_attendee_row():
    client, received = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees/from-calendar-invite",
        json={
            "invitees": [
                {"email": "jamie@example.com", "display_name": "Jamie Rivera"},
                {"email": "alex@example.com", "display_name": "Alex Chen"},
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert [a["display_name"] for a in body] == ["Jamie Rivera", "Alex Chen"]
    assert all(a["meeting_id"] == "meeting-1" for a in body)
    assert all(a["id"] for a in body)

    assert [payload.display_name for _, payload in received] == [
        "Jamie Rivera",
        "Alex Chen",
    ]


def test_an_invitee_without_a_display_name_falls_back_to_their_email():
    client, received = make_client()

    client.post(
        "/api/meetings/meeting-1/attendees/from-calendar-invite",
        json={"invitees": [{"email": "jamie@example.com"}]},
    )

    assert received[0][1].display_name == "jamie@example.com"


def test_an_invitee_carries_no_structured_profile_fields():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees/from-calendar-invite",
        json={"invitees": [{"email": "jamie@example.com"}]},
    )

    attendee = response.json()[0]
    assert attendee["role"] is None
    assert attendee["business_function"] is None
    assert attendee["decision_authority"] is None
    assert attendee["domain_expertise"] == []


def test_a_calendar_invite_with_no_invitees_persists_no_attendees():
    client, received = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees/from-calendar-invite",
        json={"invitees": []},
    )

    assert response.status_code == 201
    assert response.json() == []
    assert received == []


def test_an_invitee_without_an_email_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/attendees/from-calendar-invite",
        json={"invitees": [{"display_name": "Jamie Rivera"}]},
    )

    assert response.status_code == 422
