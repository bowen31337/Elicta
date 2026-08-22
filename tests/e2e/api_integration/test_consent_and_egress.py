"""Happy-path 200/201 and documented-4xx coverage for consent + egress-audit."""

from __future__ import annotations

from app.core.consent.models import ConsentModel
from fastapi.testclient import TestClient

from conftest import Backend


def test_get_consent_gate_returns_200(client: TestClient, backend: Backend) -> None:
    backend.consent_models["e1"] = ConsentModel.PER_MEETING

    response = client.get("/api/meetings/m1/consent-gate", params={"engagement_id": "e1"})

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_confirmation"


def test_get_consent_gate_missing_required_query_param_returns_422(client: TestClient) -> None:
    response = client.get("/api/meetings/m1/consent-gate")

    assert response.status_code == 422


def test_confirm_consent_returns_201(client: TestClient, backend: Backend) -> None:
    response = client.post(
        "/api/meetings/m1/consent-confirmation", json={"confirmed_by": "operator-1"}
    )

    assert response.status_code == 201
    assert response.json()["meeting_id"] == "m1"
    assert len(backend.consent_records) == 1


def test_confirm_consent_blank_operator_returns_422(client: TestClient) -> None:
    response = client.post("/api/meetings/m1/consent-confirmation", json={"confirmed_by": ""})

    assert response.status_code == 422


def test_get_egress_audit_log_returns_200(client: TestClient, backend: Backend) -> None:
    from app.core.egress.models import EgressLogRow

    backend.egress_rows.append(
        EgressLogRow(
            timestamp_ms=1_000,
            engagement_id="e1",
            processor_name="deepgram",
            region="us",
            byte_count=128,
            success=True,
        )
    )

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "e1", "start_ms": 0, "end_ms": 2_000},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_egress_audit_log_end_before_start_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "e1", "start_ms": 2_000, "end_ms": 0},
    )

    assert response.status_code == 422


def test_engagement_level_consent_admits_capture_without_a_per_meeting_confirmation(
    client: TestClient, backend: Backend
) -> None:
    """The gate and capture admission agree about the second consent model.

    `admit_capture` used to test membership of `confirmed_meetings` -- the
    record a *per-meeting* confirmation leaves -- instead of evaluating the
    gate. An engagement that captured consent once for the engagement as a
    whole writes no such record, so `evaluate_consent_gate` answered
    `not_required` with `capture_may_begin` true while capture admission
    refused the same meeting with 403. One decision, two halves, disagreeing.

    This lives here rather than in `test_consent_gate_seam.py` because it has
    to seed the consent model: no API sets one, a gap declared in
    `test_composition_seams.ACCEPTED_READ_ONLY`, and the seam suite forbids
    setting up state on the backend for good reason. What is seeded is the
    engagement's *configuration*, not the read side of the pair under test --
    the meeting, its engagement mapping and the session start all go through
    the API.
    """

    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Harbourline Ferries",
            "sector": "transport",
            "commercial_context": "Standing consent agreed at kickoff",
        },
    )
    assert engagement.status_code == 201, engagement.text
    engagement_id = engagement.json()["engagement_id"]

    meeting = client.post(
        "/api/meetings", json={"engagement_id": engagement_id, "capture_mode": "live"}
    )
    assert meeting.status_code == 201, meeting.text
    meeting_id = meeting.json()["meeting_id"]

    backend.consent_models[engagement_id] = ConsentModel.ENGAGEMENT_LEVEL

    gate = client.get(
        f"/api/meetings/{meeting_id}/consent-gate", params={"engagement_id": engagement_id}
    )
    assert gate.status_code == 200, gate.text
    assert gate.json()["status"] == "not_required"

    started = client.post(f"/api/meetings/{meeting_id}/session/start")

    assert started.status_code == 200, (
        "the gate says capture may begin; admission refused it anyway: " + started.text
    )
    assert started.json()["meeting_id"] == meeting_id


def _per_meeting_engagement(client: TestClient, backend: Backend) -> tuple[str, str]:
    """An engagement that asks for consent at every meeting, and one meeting on it.

    Seeded, because `DEFAULT_CONSENT_MODEL` is `ENGAGEMENT_LEVEL` and no API
    sets a consent model. Everything else — the engagement, the meeting, the
    confirmation, the session start — goes through the API.
    """

    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Harbourline Ferries",
            "sector": "transport",
            "commercial_context": "Requirements discovery for crew rostering",
        },
    )
    assert engagement.status_code == 201, engagement.text
    engagement_id = engagement.json()["engagement_id"]
    backend.consent_models[engagement_id] = ConsentModel.PER_MEETING

    meeting = client.post(
        "/api/meetings", json={"engagement_id": engagement_id, "capture_mode": "live"}
    )
    assert meeting.status_code == 201, meeting.text
    return engagement_id, meeting.json()["meeting_id"]


def test_a_per_meeting_confirmation_is_visible_to_the_gate(
    client: TestClient, backend: Backend
) -> None:
    """The original live-run defect, kept under test after the default flipped.

    `save_consent_record` wrote `consent_records` while the gate read
    `confirmed_meetings`, so consent was captured perfectly and read back as
    never given. This lived in `test_consent_gate_seam.py` while every
    engagement asked for consent by default; it moved here when the stage
    default became `ENGAGEMENT_LEVEL`, because reproducing the asking model
    now needs a seeded consent model and the seam suite forbids seeding.
    """

    engagement_id, meeting_id = _per_meeting_engagement(client, backend)

    before = client.get(
        f"/api/meetings/{meeting_id}/consent-gate", params={"engagement_id": engagement_id}
    )
    assert before.status_code == 200, before.text
    assert before.json()["status"] == "awaiting_confirmation"
    assert before.json()["prompt"] is not None

    confirmed = client.post(
        f"/api/meetings/{meeting_id}/consent-confirmation",
        json={"confirmed_by": "Dana Whitlock"},
    )
    assert confirmed.status_code == 201, confirmed.text

    after = client.get(
        f"/api/meetings/{meeting_id}/consent-gate", params={"engagement_id": engagement_id}
    )
    assert after.status_code == 200, after.text
    assert after.json()["status"] == "confirmed"


def test_per_meeting_capture_is_refused_before_consent_and_allowed_after(
    client: TestClient, backend: Backend
) -> None:
    """The gate still guards capture wherever the asking model is in force."""

    _engagement_id, meeting_id = _per_meeting_engagement(client, backend)

    refused = client.post(f"/api/meetings/{meeting_id}/session/start")
    assert refused.status_code == 403, refused.text
    detail = refused.json()["detail"]
    assert "consent" in detail.lower(), f"the refusal does not name consent: {detail!r}"
    assert "not found" not in detail.lower(), (
        "the meeting exists; refusing it as missing is the right answer for the wrong reason"
    )

    client.post(
        f"/api/meetings/{meeting_id}/consent-confirmation",
        json={"confirmed_by": "Dana Whitlock"},
    )

    allowed = client.post(f"/api/meetings/{meeting_id}/session/start")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["meeting_id"] == meeting_id


def test_per_meeting_consent_for_one_meeting_does_not_open_the_gate_for_another(
    client: TestClient, backend: Backend
) -> None:
    """Under the asking model the gate is per meeting (PRD D3)."""

    _first_engagement, first = _per_meeting_engagement(client, backend)
    _second_engagement, second = _per_meeting_engagement(client, backend)

    client.post(
        f"/api/meetings/{first}/consent-confirmation", json={"confirmed_by": "Dana Whitlock"}
    )

    assert client.post(f"/api/meetings/{first}/session/start").status_code == 200
    assert client.post(f"/api/meetings/{second}/session/start").status_code == 403
