"""Confirming consent opens the consent gate, and the gate guards capture.

The defect this covers: `save_consent_record` appended to
`backend.consent_records` while `is_confirmed_for_meeting` read
`backend.confirmed_meetings`, which nothing wrote. Consent was recorded
correctly and read back as never given — and because the live-session route
never consulted the gate at all, "session refused before consent" passed for
the wrong reason: the service simply could not find the meeting.

Both halves are asserted here through the API only, in order: refused before,
allowed after.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_meeting(client: TestClient) -> tuple[str, str]:
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

    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return engagement_id, meeting.json()["meeting_id"]


def test_consent_confirmation_is_visible_to_the_gate(client: TestClient) -> None:
    engagement_id, meeting_id = _create_meeting(client)

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


def test_capture_is_refused_before_consent_and_allowed_after(client: TestClient) -> None:
    _engagement_id, meeting_id = _create_meeting(client)

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


def test_consent_for_one_meeting_does_not_open_the_gate_for_another(client: TestClient) -> None:
    """The gate is per meeting (PRD D3's per-meeting consent model)."""

    _engagement_id, first = _create_meeting(client)
    _other_engagement_id, second = _create_meeting(client)

    client.post(
        f"/api/meetings/{first}/consent-confirmation", json={"confirmed_by": "Dana Whitlock"}
    )

    assert client.post(f"/api/meetings/{first}/session/start").status_code == 200
    assert client.post(f"/api/meetings/{second}/session/start").status_code == 403


def test_a_confirmation_names_who_gave_it_when_read_back(client: TestClient) -> None:
    """Consent was write-only in the one way an audit cares about.

    The gate could say capture may begin; nothing could say on whose word.
    The confirmation was written to a durable record and served back nowhere,
    so the consent screen could show "on record" with no name against it.
    """

    _, meeting_id = _create_meeting(client)
    confirmed = client.post(
        f"/api/meetings/{meeting_id}/consent-confirmation",
        json={"confirmed_by": "Priya Raman"},
    )
    assert confirmed.status_code == 201, confirmed.text

    response = client.get(f"/api/meetings/{meeting_id}/consent-record")

    assert response.status_code == 200, response.text
    record = response.json()
    assert record["meeting_id"] == meeting_id
    assert record["confirmed_by"] == "Priya Raman"
    assert record["confirmed_at"]


def test_an_unconfirmed_meeting_has_no_consent_record(client: TestClient) -> None:
    _, meeting_id = _create_meeting(client)

    assert client.get(f"/api/meetings/{meeting_id}/consent-record").status_code == 404
