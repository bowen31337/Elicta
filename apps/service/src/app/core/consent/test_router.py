from app.core.consent.models import ConsentModel
from app.core.consent.router import build_consent_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_client(consent_model: ConsentModel, confirmed: bool) -> TestClient:
    async def get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return consent_model

    async def is_confirmed_for_meeting(meeting_id: str) -> bool:
        return confirmed

    app = FastAPI()
    app.include_router(
        build_consent_router(get_engagement_consent_model, is_confirmed_for_meeting)
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
