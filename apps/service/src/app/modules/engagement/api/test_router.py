from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.engagement.api.router import build_engagement_router
from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)


def make_client(
    engagement_id: str = "e1",
    existing_engagements: set[str] | None = None,
) -> tuple[
    TestClient,
    list[EngagementCreateRequest],
    list[tuple[str, EngagementUpdateRequest]],
]:
    received_creates: list[EngagementCreateRequest] = []
    received_updates: list[tuple[str, EngagementUpdateRequest]] = []
    known_ids = existing_engagements if existing_engagements is not None else {engagement_id}

    async def create_engagement(payload: EngagementCreateRequest) -> str:
        received_creates.append(payload)
        return engagement_id

    async def update_engagement(
        target_id: str, payload: EngagementUpdateRequest
    ) -> EngagementUpdateResponse | None:
        received_updates.append((target_id, payload))
        if target_id not in known_ids:
            return None
        return EngagementUpdateResponse(
            engagement_id=target_id,
            purpose=payload.purpose,
            scope_boundary=payload.scope_boundary,
            target_requirements_template=payload.target_requirements_template,
        )

    app = FastAPI()
    app.include_router(build_engagement_router(create_engagement, update_engagement))
    return TestClient(app), received_creates, received_updates


def test_creating_an_engagement_returns_201_with_engagement_id():
    client, _, _ = make_client(engagement_id="eng-123")

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
    client, received_creates, _ = make_client()

    client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Corp",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert len(received_creates) == 1
    assert received_creates[0].client_organisation == "Acme Corp"
    assert received_creates[0].sector == "Manufacturing"
    assert received_creates[0].commercial_context == "Multi-year cost reduction programme"


def test_missing_required_field_is_rejected():
    client, _, _ = make_client()

    response = client.post(
        "/api/engagements",
        json={"client_organisation": "Acme Corp", "sector": "Manufacturing"},
    )

    assert response.status_code == 422


def test_blank_required_field_is_rejected():
    client, _, _ = make_client()

    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert response.status_code == 422


def test_updating_an_engagement_returns_200_with_updated_fields():
    client, _, _ = make_client(engagement_id="eng-123")

    response = client.patch(
        "/api/engagements/eng-123",
        json={
            "purpose": "Reduce manufacturing cost base",
            "scope_boundary": "Excludes logistics and warehousing",
            "target_requirements_template": "MoSCoW",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "engagement_id": "eng-123",
        "purpose": "Reduce manufacturing cost base",
        "scope_boundary": "Excludes logistics and warehousing",
        "target_requirements_template": "MoSCoW",
    }


def test_updating_an_engagement_passes_fields_through():
    client, _, received_updates = make_client(engagement_id="eng-123")

    client.patch(
        "/api/engagements/eng-123",
        json={
            "purpose": "Reduce manufacturing cost base",
            "scope_boundary": "Excludes logistics and warehousing",
            "target_requirements_template": "MoSCoW",
        },
    )

    assert len(received_updates) == 1
    target_id, payload = received_updates[0]
    assert target_id == "eng-123"
    assert payload.purpose == "Reduce manufacturing cost base"
    assert payload.scope_boundary == "Excludes logistics and warehousing"
    assert payload.target_requirements_template == "MoSCoW"


def test_updating_a_single_field_is_allowed():
    client, _, _ = make_client(engagement_id="eng-123")

    response = client.patch(
        "/api/engagements/eng-123",
        json={"purpose": "Reduce manufacturing cost base"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["purpose"] == "Reduce manufacturing cost base"
    assert body["scope_boundary"] is None
    assert body["target_requirements_template"] is None


def test_updating_an_unknown_engagement_returns_404():
    client, _, _ = make_client(engagement_id="eng-123", existing_engagements=set())

    response = client.patch(
        "/api/engagements/does-not-exist",
        json={"purpose": "Reduce manufacturing cost base"},
    )

    assert response.status_code == 404


def test_updating_with_no_fields_is_rejected():
    client, _, _ = make_client(engagement_id="eng-123")

    response = client.patch("/api/engagements/eng-123", json={})

    assert response.status_code == 422


def test_updating_with_a_blank_field_is_rejected():
    client, _, _ = make_client(engagement_id="eng-123")

    response = client.patch(
        "/api/engagements/eng-123",
        json={"purpose": ""},
    )

    assert response.status_code == 422
