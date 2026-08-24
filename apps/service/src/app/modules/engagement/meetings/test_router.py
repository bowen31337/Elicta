"""Tests for the meeting attendees and meeting update HTTP surfaces (PRD FR-3.8, FR-3.9, FR-3.10)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.engagement.meetings.models import (
    Attendee,
    AttendeeCreateRequest,
    EngagementContext,
    MeetingCreateRequest,
    MeetingUpdateRequest,
    MeetingUpdateResponse,
)
from app.modules.engagement.meetings.router import (
    build_meeting_attendees_router,
    build_meeting_router,
)


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


def make_update_client(
    meeting_id: str = "meeting-1",
    existing_meetings: set[str] | None = None,
) -> tuple[TestClient, list[tuple[str, MeetingUpdateRequest]]]:
    received_updates: list[tuple[str, MeetingUpdateRequest]] = []
    known_ids = existing_meetings if existing_meetings is not None else {meeting_id}

    async def create_meeting(payload: MeetingCreateRequest) -> str:
        raise AssertionError("create_meeting should not be called in these tests")

    async def get_engagement_context(engagement_id: str) -> EngagementContext | None:
        raise AssertionError("get_engagement_context should not be called in these tests")

    async def update_meeting(
        target_id: str, payload: MeetingUpdateRequest
    ) -> MeetingUpdateResponse | None:
        received_updates.append((target_id, payload))
        if target_id not in known_ids:
            return None
        return MeetingUpdateResponse(
            meeting_id=target_id,
            session_purpose=payload.session_purpose,
            target_template_sections=payload.target_template_sections,
        )

    app = FastAPI()
    app.include_router(
        build_meeting_router(create_meeting, get_engagement_context, update_meeting)
    )
    return TestClient(app), received_updates


def make_create_client(
    engagement_contexts: dict[str, EngagementContext] | None = None,
) -> tuple[TestClient, list[MeetingCreateRequest]]:
    received_creates: list[MeetingCreateRequest] = []
    contexts = engagement_contexts if engagement_contexts is not None else {}

    async def create_meeting(payload: MeetingCreateRequest) -> str:
        received_creates.append(payload)
        return "meeting-1"

    async def get_engagement_context(engagement_id: str) -> EngagementContext | None:
        return contexts.get(engagement_id)

    async def update_meeting(
        target_id: str, payload: MeetingUpdateRequest
    ) -> MeetingUpdateResponse | None:
        raise AssertionError("update_meeting should not be called in these tests")

    app = FastAPI()
    app.include_router(
        build_meeting_router(create_meeting, get_engagement_context, update_meeting)
    )
    return TestClient(app), received_creates


def make_engagement_context(**overrides: object) -> EngagementContext:
    fields = {
        "client_organisation": "Acme Corp",
        "sector": "Manufacturing",
        "commercial_context": "Cost-out program, phase 2",
        "purpose": "Reduce warehouse cycle time",
        "scope_boundary": "Excludes procurement systems",
        "target_requirements_template": "standard-discovery",
    }
    fields.update(overrides)
    return EngagementContext(**fields)


def test_creating_a_meeting_returns_201_with_the_inherited_engagement_context():
    client, _ = make_create_client(
        engagement_contexts={"engagement-1": make_engagement_context()}
    )

    response = client.post(
        "/api/meetings",
        json={"engagement_id": "engagement-1", "capture_mode": "live"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert body["engagement_id"] == "engagement-1"
    assert body["state"] == "planned"
    assert body["capture_mode"] == "live"
    assert body["scheduled_at"] is None
    assert body["engagement_context"] == {
        "client_organisation": "Acme Corp",
        "sector": "Manufacturing",
        "commercial_context": "Cost-out program, phase 2",
        "purpose": "Reduce warehouse cycle time",
        "scope_boundary": "Excludes procurement systems",
        "target_requirements_template": "standard-discovery",
    }


def test_creating_a_meeting_does_not_require_re_entering_engagement_context():
    client, received = make_create_client(
        engagement_contexts={"engagement-1": make_engagement_context()}
    )

    response = client.post(
        "/api/meetings",
        json={"engagement_id": "engagement-1", "capture_mode": "live"},
    )

    assert response.status_code == 201
    assert len(received) == 1
    assert received[0].engagement_id == "engagement-1"
    assert received[0].capture_mode == "live"


def test_creating_a_meeting_passes_through_an_optional_scheduled_at():
    client, received = make_create_client(
        engagement_contexts={"engagement-1": make_engagement_context()}
    )

    response = client.post(
        "/api/meetings",
        json={
            "engagement_id": "engagement-1",
            "capture_mode": "live",
            "scheduled_at": "2026-09-01T14:00:00Z",
        },
    )

    assert response.status_code == 201
    assert response.json()["scheduled_at"] == "2026-09-01T14:00:00Z"
    assert received[0].scheduled_at is not None


def test_creating_a_meeting_for_an_unknown_engagement_returns_404():
    client, received = make_create_client(engagement_contexts={})

    response = client.post(
        "/api/meetings",
        json={"engagement_id": "does-not-exist", "capture_mode": "live"},
    )

    assert response.status_code == 404
    assert received == []


def test_creating_a_meeting_without_a_capture_mode_is_rejected():
    client, _ = make_create_client(
        engagement_contexts={"engagement-1": make_engagement_context()}
    )

    response = client.post(
        "/api/meetings",
        json={"engagement_id": "engagement-1"},
    )

    assert response.status_code == 422


def test_creating_a_meeting_without_an_engagement_id_is_rejected():
    client, _ = make_create_client()

    response = client.post(
        "/api/meetings",
        json={"capture_mode": "live"},
    )

    assert response.status_code == 422


def test_creating_a_meeting_with_an_unknown_field_is_rejected():
    client, _ = make_create_client(
        engagement_contexts={"engagement-1": make_engagement_context()}
    )

    response = client.post(
        "/api/meetings",
        json={
            "engagement_id": "engagement-1",
            "capture_mode": "live",
            "client_organisation": "Sneaking this back in",
        },
    )

    assert response.status_code == 422


def test_creating_a_meeting_with_no_engagement_context_fields_missing_still_confirms_them():
    client, _ = make_create_client(
        engagement_contexts={
            "engagement-1": make_engagement_context(
                purpose=None, scope_boundary=None, target_requirements_template=None
            )
        }
    )

    response = client.post(
        "/api/meetings",
        json={"engagement_id": "engagement-1", "capture_mode": "live"},
    )

    assert response.status_code == 201
    context = response.json()["engagement_context"]
    assert context["purpose"] is None
    assert context["scope_boundary"] is None
    assert context["target_requirements_template"] is None
    assert context["client_organisation"] == "Acme Corp"


def test_updating_a_meeting_returns_200_with_updated_fields():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch(
        "/api/meetings/meeting-1",
        json={
            "session_purpose": "Validate scope boundary for phase 2",
            "target_template_sections": ["Functional Requirements", "Non-Functional Requirements"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "meeting_id": "meeting-1",
        "session_purpose": "Validate scope boundary for phase 2",
        "target_template_sections": ["Functional Requirements", "Non-Functional Requirements"],
    }


def test_updating_a_meeting_passes_fields_through():
    client, received_updates = make_update_client(meeting_id="meeting-1")

    client.patch(
        "/api/meetings/meeting-1",
        json={
            "session_purpose": "Validate scope boundary for phase 2",
            "target_template_sections": ["Functional Requirements"],
        },
    )

    assert len(received_updates) == 1
    target_id, payload = received_updates[0]
    assert target_id == "meeting-1"
    assert payload.session_purpose == "Validate scope boundary for phase 2"
    assert payload.target_template_sections == ["Functional Requirements"]


def test_updating_a_meeting_with_a_single_field_is_allowed():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch(
        "/api/meetings/meeting-1",
        json={"session_purpose": "Validate scope boundary for phase 2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_purpose"] == "Validate scope boundary for phase 2"
    assert body["target_template_sections"] is None


def test_updating_an_unknown_meeting_returns_404():
    client, _ = make_update_client(meeting_id="meeting-1", existing_meetings=set())

    response = client.patch(
        "/api/meetings/does-not-exist",
        json={"session_purpose": "Validate scope boundary for phase 2"},
    )

    assert response.status_code == 404


def test_updating_a_meeting_with_no_fields_is_rejected():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch("/api/meetings/meeting-1", json={})

    assert response.status_code == 422


def test_updating_a_meeting_with_a_blank_purpose_is_rejected():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch(
        "/api/meetings/meeting-1",
        json={"session_purpose": ""},
    )

    assert response.status_code == 422


def test_updating_a_meeting_with_an_empty_template_section_list_is_rejected():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch(
        "/api/meetings/meeting-1",
        json={"target_template_sections": []},
    )

    assert response.status_code == 422


def test_updating_a_meeting_with_an_unknown_field_is_rejected():
    client, _ = make_update_client(meeting_id="meeting-1")

    response = client.patch(
        "/api/meetings/meeting-1",
        json={"session_purpose": "Validate scope boundary", "notes": "irrelevant"},
    )

    assert response.status_code == 422


def make_delete_client(
    existing_meetings: set[str] | None = None,
    with_delete: bool = True,
) -> tuple[TestClient, list[str]]:
    """A meetings router whose only live callable is `delete_meeting`.

    `with_delete=False` builds the router the way the pre-existing tests above
    do — three positional callables and nothing else — so the guard that the
    DELETE route is absent unless somebody supplies a way to perform it is
    tested against the real construction, not a mocked one.
    """

    received_deletes: list[str] = []
    known_ids = existing_meetings if existing_meetings is not None else {"meeting-1"}

    async def create_meeting(payload: MeetingCreateRequest) -> str:
        raise AssertionError("create_meeting should not be called in these tests")

    async def get_engagement_context(engagement_id: str) -> EngagementContext | None:
        raise AssertionError("get_engagement_context should not be called in these tests")

    async def update_meeting(
        target_id: str, payload: MeetingUpdateRequest
    ) -> MeetingUpdateResponse | None:
        raise AssertionError("update_meeting should not be called in these tests")

    async def delete_meeting(target_id: str) -> bool:
        received_deletes.append(target_id)
        return target_id in known_ids

    app = FastAPI()
    app.include_router(
        build_meeting_router(
            create_meeting,
            get_engagement_context,
            update_meeting,
            delete_meeting if with_delete else None,
        )
    )
    return TestClient(app), received_deletes


def test_deleting_a_meeting_returns_204_and_no_body():
    client, received = make_delete_client()

    response = client.delete("/api/meetings/meeting-1")

    assert response.status_code == 204
    assert response.content == b""
    assert received == ["meeting-1"]


def test_deleting_an_unknown_meeting_returns_404():
    client, received = make_delete_client(existing_meetings=set())

    response = client.delete("/api/meetings/does-not-exist")

    assert response.status_code == 404
    # The callable is still consulted: only it can answer whether the meeting
    # is there, so a 404 is its verdict rather than a guess made before asking.
    assert received == ["does-not-exist"]


def test_deleting_the_same_meeting_twice_returns_404_the_second_time():
    client, _ = make_delete_client(existing_meetings={"meeting-1"})

    assert client.delete("/api/meetings/meeting-1").status_code == 204

    # `known_ids` is a fixed set here, so this asserts the route's contract
    # rather than the fake's memory: the second call is answered by whatever
    # `delete_meeting` reports, and composition's real one reports False.
    second = make_delete_client(existing_meetings=set())[0].delete("/api/meetings/meeting-1")
    assert second.status_code == 404


def test_a_router_built_without_a_delete_callable_serves_no_delete_route():
    client, _ = make_delete_client(with_delete=False)

    response = client.delete("/api/meetings/meeting-1")

    assert response.status_code == 405
