"""A confirmation is readable afterwards, and capture is admitted at this stage.

The defect this covers: `save_consent_record` appended to
`backend.consent_records` while `is_confirmed_for_meeting` read
`backend.confirmed_meetings`, which nothing wrote. Consent was recorded
correctly and read back as never given.

Everything here goes through the API only, which is the point of a seam test.
That is also why the *asking* consent model is no longer exercised here:
`DEFAULT_CONSENT_MODEL` is `ENGAGEMENT_LEVEL`, so an engagement created
through the API never asks for a per-meeting confirmation, and reaching
`PER_MEETING` needs a seeded consent model that this suite rightly forbids.
Those assertions were not dropped — they moved to
`test_consent_and_egress.py`, where the model is seeded explicitly and the
refused-before/allowed-after pair is still asserted in full.
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


def test_capture_is_admitted_without_a_confirmation_at_this_stage(client: TestClient) -> None:
    """The stage default, asserted end to end rather than left to inference.

    `DEFAULT_CONSENT_MODEL` is `ENGAGEMENT_LEVEL`, so a meeting created
    through the API may begin capture with nothing confirmed. This is the
    fail-open direction, and it is asserted explicitly so that the day the
    default goes back to `PER_MEETING` this test fails and says so, rather
    than the change landing silently.
    """

    engagement_id, meeting_id = _create_meeting(client)

    gate = client.get(
        f"/api/meetings/{meeting_id}/consent-gate", params={"engagement_id": engagement_id}
    )
    assert gate.status_code == 200, gate.text
    assert gate.json()["status"] == "not_required"
    assert gate.json()["prompt"] is None, "a gate that is not asking must not carry a prompt"

    started = client.post(f"/api/meetings/{meeting_id}/session/start")

    assert started.status_code == 200, started.text
    assert started.json()["meeting_id"] == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}/consent-record").status_code == 404, (
        "nothing was confirmed, so nothing may claim to be on record"
    )
