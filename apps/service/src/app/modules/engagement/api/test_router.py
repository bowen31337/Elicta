from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.engagement.api.router import build_engagement_router
from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementRecord,
    EngagementSummary,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)


def make_client(
    engagement_id: str = "e1",
    existing_engagements: set[str] | None = None,
    engagements: dict[str, EngagementRecord] | None = None,
    document_counts: dict[str, int] | None = None,
    engagement_list: list[EngagementSummary] | None = None,
) -> tuple[
    TestClient,
    list[EngagementCreateRequest],
    list[tuple[str, EngagementUpdateRequest]],
    list[tuple[int, int]],
]:
    received_creates: list[EngagementCreateRequest] = []
    received_updates: list[tuple[str, EngagementUpdateRequest]] = []
    received_list_calls: list[tuple[int, int]] = []
    known_ids = existing_engagements if existing_engagements is not None else {engagement_id}
    records = engagements if engagements is not None else {}
    counts = document_counts if document_counts is not None else {}
    all_engagements = engagement_list if engagement_list is not None else []

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

    async def get_engagement(target_id: str) -> EngagementRecord | None:
        return records.get(target_id)

    async def get_document_count(target_id: str) -> int:
        return counts.get(target_id, 0)

    async def list_engagements(page: int, page_size: int) -> tuple[list[EngagementSummary], int]:
        received_list_calls.append((page, page_size))
        start = (page - 1) * page_size
        end = start + page_size
        return all_engagements[start:end], len(all_engagements)

    app = FastAPI()
    app.include_router(
        build_engagement_router(
            create_engagement,
            update_engagement,
            get_engagement=get_engagement,
            get_document_count=get_document_count,
            list_engagements=list_engagements,
        )
    )
    return TestClient(app), received_creates, received_updates, received_list_calls


def test_creating_an_engagement_returns_201_with_engagement_id():
    client, _, _, _ = make_client(engagement_id="eng-123")

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
    client, received_creates, _, _ = make_client()

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
    client, _, _, _ = make_client()

    response = client.post(
        "/api/engagements",
        json={"client_organisation": "Acme Corp", "sector": "Manufacturing"},
    )

    assert response.status_code == 422


def test_blank_required_field_is_rejected():
    client, _, _, _ = make_client()

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
    client, _, _, _ = make_client(engagement_id="eng-123")

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
    client, _, received_updates, _ = make_client(engagement_id="eng-123")

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
    client, _, _, _ = make_client(engagement_id="eng-123")

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
    client, _, _, _ = make_client(engagement_id="eng-123", existing_engagements=set())

    response = client.patch(
        "/api/engagements/does-not-exist",
        json={"purpose": "Reduce manufacturing cost base"},
    )

    assert response.status_code == 404


def test_updating_with_no_fields_is_rejected():
    client, _, _, _ = make_client(engagement_id="eng-123")

    response = client.patch("/api/engagements/eng-123", json={})

    assert response.status_code == 422


def test_updating_with_a_blank_field_is_rejected():
    client, _, _, _ = make_client(engagement_id="eng-123")

    response = client.patch(
        "/api/engagements/eng-123",
        json={"purpose": ""},
    )

    assert response.status_code == 422


def test_getting_an_engagement_returns_200_with_document_count_and_score():
    client, _, _, _ = make_client(
        engagements={
            "eng-123": EngagementRecord(
                client_organisation="Acme Corp",
                sector="Manufacturing",
                commercial_context="Multi-year cost reduction programme",
                purpose="Reduce manufacturing cost base",
            )
        },
        document_counts={"eng-123": 4},
    )

    response = client.get("/api/engagements/eng-123")

    assert response.status_code == 200
    assert response.json() == {
        "engagement_id": "eng-123",
        "client_organisation": "Acme Corp",
        "sector": "Manufacturing",
        "commercial_context": "Multi-year cost reduction programme",
        "purpose": "Reduce manufacturing cost base",
        "scope_boundary": None,
        "target_requirements_template": None,
        "document_count": 4,
        "context_completeness_score": 4 / 6,
    }


def test_getting_an_unknown_engagement_returns_404():
    client, _, _, _ = make_client(engagements={})

    response = client.get("/api/engagements/does-not-exist")

    assert response.status_code == 404


def test_getting_an_engagement_with_no_documents_returns_zero_count():
    client, _, _, _ = make_client(
        engagements={
            "eng-123": EngagementRecord(
                client_organisation="Acme Corp",
                sector="Manufacturing",
                commercial_context="Multi-year cost reduction programme",
            )
        },
    )

    response = client.get("/api/engagements/eng-123")

    assert response.status_code == 200
    body = response.json()
    assert body["document_count"] == 0
    assert body["context_completeness_score"] == 0.5


def test_listing_engagements_returns_200_with_a_page_of_items():
    client, _, _, _ = make_client(
        engagement_list=[
            EngagementSummary(
                engagement_id="eng-1",
                client_organisation="Acme Corp",
                sector="Manufacturing",
                commercial_context="Multi-year cost reduction programme",
            ),
            EngagementSummary(
                engagement_id="eng-2",
                client_organisation="Globex",
                sector="Retail",
                commercial_context="Store footprint rationalisation",
            ),
        ],
    )

    response = client.get("/api/engagements")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "engagement_id": "eng-1",
                "client_organisation": "Acme Corp",
                "sector": "Manufacturing",
                "commercial_context": "Multi-year cost reduction programme",
                "purpose": None,
                "scope_boundary": None,
                "target_requirements_template": None,
            },
            {
                "engagement_id": "eng-2",
                "client_organisation": "Globex",
                "sector": "Retail",
                "commercial_context": "Store footprint rationalisation",
                "purpose": None,
                "scope_boundary": None,
                "target_requirements_template": None,
            },
        ],
        "total": 2,
        "page": 1,
        "page_size": 20,
    }


def test_listing_engagements_with_no_engagements_returns_an_empty_page():
    client, _, _, _ = make_client(engagement_list=[])

    response = client.get("/api/engagements")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_listing_engagements_passes_page_and_page_size_through():
    client, _, _, received_list_calls = make_client(
        engagement_list=[
            EngagementSummary(
                engagement_id=f"eng-{i}",
                client_organisation="Acme Corp",
                sector="Manufacturing",
                commercial_context="Multi-year cost reduction programme",
            )
            for i in range(5)
        ],
    )

    response = client.get("/api/engagements", params={"page": 2, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 5
    assert [item["engagement_id"] for item in body["items"]] == ["eng-2", "eng-3"]
    assert received_list_calls == [(2, 2)]


def test_listing_engagements_defaults_to_page_1_and_page_size_20():
    client, _, _, received_list_calls = make_client(engagement_list=[])

    client.get("/api/engagements")

    assert received_list_calls == [(1, 20)]


def test_listing_engagements_rejects_a_page_below_1():
    client, _, _, _ = make_client(engagement_list=[])

    response = client.get("/api/engagements", params={"page": 0})

    assert response.status_code == 422


def test_listing_engagements_rejects_a_page_size_above_100():
    client, _, _, _ = make_client(engagement_list=[])

    response = client.get("/api/engagements", params={"page_size": 101})

    assert response.status_code == 422
