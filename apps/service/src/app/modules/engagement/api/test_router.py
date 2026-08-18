from app.modules.engagement.api.router import build_engagement_router
from app.modules.engagement.api.schemas import EngagementCreateRequest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_client(
    engagement_id: str = "e1",
) -> tuple[TestClient, list[EngagementCreateRequest]]:
    received: list[EngagementCreateRequest] = []

    async def create_engagement(payload: EngagementCreateRequest) -> str:
        received.append(payload)
        return engagement_id

    app = FastAPI()
    app.include_router(build_engagement_router(create_engagement))
    return TestClient(app), received


def test_creating_an_engagement_returns_201_with_engagement_id():
    client, _ = make_client(engagement_id="eng-123")

    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Corp",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"engagement_id": "eng-123"}


def test_creating_an_engagement_passes_client_background_through():
    client, received = make_client()

    client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Corp",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert len(received) == 1
    assert received[0].client_organisation == "Acme Corp"
    assert received[0].sector == "Manufacturing"
    assert received[0].commercial_context == "Multi-year cost reduction programme"


def test_missing_required_field_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/engagements",
        json={"client_organisation": "Acme Corp", "sector": "Manufacturing"},
    )

    assert response.status_code == 422


def test_blank_required_field_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert response.status_code == 422
