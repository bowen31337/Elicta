from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .errors import EngagementNotFoundError
from .router import build_vocabulary_router
from .schemas import VocabularyTermCreateRequest


def make_client(
    term_id: str | Exception = "term-1",
) -> tuple[TestClient, list[tuple[str, VocabularyTermCreateRequest]]]:
    received: list[tuple[str, VocabularyTermCreateRequest]] = []

    async def add_vocabulary_term(
        engagement_id: str, payload: VocabularyTermCreateRequest
    ) -> str:
        received.append((engagement_id, payload))
        if isinstance(term_id, Exception):
            raise term_id
        return term_id

    app = FastAPI()
    app.include_router(build_vocabulary_router(add_vocabulary_term))
    return TestClient(app), received


def test_adding_a_product_name_returns_201_with_the_term():
    client, _ = make_client(term_id="term-123")

    response = client.post(
        "/api/engagements/eng-1/vocabulary",
        json={"term": "Nimbus Ledger", "term_type": "product_name"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "term_id": "term-123",
        "engagement_id": "eng-1",
        "term": "Nimbus Ledger",
        "term_type": "product_name",
    }


def test_adding_an_internal_system_passes_engagement_id_and_payload_through():
    client, received = make_client()

    client.post(
        "/api/engagements/eng-42/vocabulary",
        json={"term": "Project Falcon CRM", "term_type": "internal_system"},
    )

    assert len(received) == 1
    engagement_id, payload = received[0]
    assert engagement_id == "eng-42"
    assert payload.term == "Project Falcon CRM"
    assert payload.term_type == "internal_system"


def test_adding_an_acronym_is_accepted():
    client, _ = make_client()

    response = client.post(
        "/api/engagements/eng-1/vocabulary",
        json={"term": "SLA", "term_type": "acronym"},
    )

    assert response.status_code == 201
    assert response.json()["term_type"] == "acronym"


def test_missing_required_field_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/engagements/eng-1/vocabulary",
        json={"term": "Nimbus Ledger"},
    )

    assert response.status_code == 422


def test_blank_term_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/engagements/eng-1/vocabulary",
        json={"term": "", "term_type": "product_name"},
    )

    assert response.status_code == 422


def test_unknown_term_type_is_rejected():
    client, _ = make_client()

    response = client.post(
        "/api/engagements/eng-1/vocabulary",
        json={"term": "Nimbus Ledger", "term_type": "client_name"},
    )

    assert response.status_code == 422


def test_unknown_engagement_returns_404():
    client, _ = make_client(term_id=EngagementNotFoundError("eng-missing"))

    response = client.post(
        "/api/engagements/eng-missing/vocabulary",
        json={"term": "Nimbus Ledger", "term_type": "product_name"},
    )

    assert response.status_code == 404
