from app.core.consent.models import ConsentModel, ConsentRecord
from app.core.consent.router import build_consent_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_client(
    consent_model: ConsentModel,
    confirmed: bool,
    saved: list[ConsentRecord] | None = None,
) -> TestClient:
    async def get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return consent_model

    async def is_confirmed_for_meeting(meeting_id: str) -> bool:
        return confirmed

    async def save_consent_record(record: ConsentRecord) -> None:
        if saved is not None:
            saved.append(record)

    app = FastAPI()
    app.include_router(
        build_consent_router(
            get_engagement_consent_model, is_confirmed_for_meeting, save_consent_record
        )
    )
    return TestClient(app)


def test_per_meeting_engagement_reports_awaiting_confirmation_with_prompt():
    client = make_client(ConsentModel.PER_MEETING, confirmed=False)

    response = client.get(
        "/api/meetings/m1/consent-gate", params={"engagement_id": "e1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["prompt"]["title"] == "Recording consent required"


def test_engagement_level_engagement_reports_not_required():
    client = make_client(ConsentModel.ENGAGEMENT_LEVEL, confirmed=False)

    response = client.get(
        "/api/meetings/m1/consent-gate", params={"engagement_id": "e1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_required"
    assert body["prompt"] is None


def test_confirmed_per_meeting_consent_allows_capture():
    client = make_client(ConsentModel.PER_MEETING, confirmed=True)

    response = client.get(
        "/api/meetings/m1/consent-gate", params={"engagement_id": "e1"}
    )

    assert response.json()["status"] == "confirmed"


def test_confirm_consent_persists_meeting_operator_and_timestamp():
    saved: list[ConsentRecord] = []
    client = make_client(ConsentModel.PER_MEETING, confirmed=False, saved=saved)

    response = client.post(
        "/api/meetings/m1/consent-confirmation",
        json={"confirmed_by": "operator-42"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_id"] == "m1"
    assert body["confirmed_by"] == "operator-42"
    assert body["confirmed_at"]
    assert len(saved) == 1
    assert saved[0].meeting_id == "m1"
    assert saved[0].confirmed_by == "operator-42"


def test_confirm_consent_rejects_blank_operator():
    client = make_client(ConsentModel.PER_MEETING, confirmed=False)

    response = client.post(
        "/api/meetings/m1/consent-confirmation",
        json={"confirmed_by": ""},
    )

    assert response.status_code == 422
