from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .errors import DocumentNotFoundError, EngagementNotFoundError
from .models import DocumentStatus, EngagementDocument
from .router import build_document_status_router, build_engagement_documents_router


def document(
    document_id: str, name: str, status: DocumentStatus
) -> EngagementDocument:
    return EngagementDocument(document_id=document_id, name=name, status=status)


def make_client(
    documents: Iterable[EngagementDocument] | Exception,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def list_documents(engagement_id: str) -> Iterable[EngagementDocument]:
        received.append(engagement_id)
        if isinstance(documents, Exception):
            raise documents
        return documents

    app = FastAPI()
    app.include_router(build_engagement_documents_router(list_documents))
    return TestClient(app), received


def make_status_client(
    result: EngagementDocument | Exception,
) -> tuple[TestClient, list[tuple[str, DocumentStatus]]]:
    received: list[tuple[str, DocumentStatus]] = []

    async def update_status(
        document_id: str, status: DocumentStatus
    ) -> EngagementDocument:
        received.append((document_id, status))
        if isinstance(result, Exception):
            raise result
        return result

    app = FastAPI()
    app.include_router(build_document_status_router(update_status))
    return TestClient(app), received


def test_listing_documents_returns_200_with_status_tags():
    client, _ = make_client(
        [
            document("doc-1", "Scoping deck", DocumentStatus.GROUND_TRUTH),
            document("doc-2", "Draft roadmap", DocumentStatus.HYPOTHESIS),
            document("doc-3", "Old scoping deck", DocumentStatus.SUPERSEDED),
        ]
    )

    response = client.get("/api/engagements/eng-1/documents")

    assert response.status_code == 200
    assert response.json() == {
        "engagement_id": "eng-1",
        "documents": [
            {"document_id": "doc-1", "name": "Scoping deck", "status": "ground truth"},
            {"document_id": "doc-2", "name": "Draft roadmap", "status": "hypothesis"},
            {
                "document_id": "doc-3",
                "name": "Old scoping deck",
                "status": "superseded",
            },
        ],
    }


def test_listing_documents_passes_engagement_id_through():
    client, received = make_client(
        [document("doc-1", "Scoping deck", DocumentStatus.GROUND_TRUTH)]
    )

    client.get("/api/engagements/eng-42/documents")

    assert received == ["eng-42"]


def test_engagement_with_no_documents_returns_empty_list():
    client, _ = make_client([])

    response = client.get("/api/engagements/eng-1/documents")

    assert response.status_code == 200
    assert response.json() == {"engagement_id": "eng-1", "documents": []}


def test_unknown_engagement_id_returns_404():
    client, _ = make_client(EngagementNotFoundError("eng-missing"))

    response = client.get("/api/engagements/eng-missing/documents")

    assert response.status_code == 404


def test_updating_document_status_returns_200_with_updated_document():
    updated = document("doc-1", "Scoping deck", DocumentStatus.SUPERSEDED)
    client, received = make_status_client(updated)

    response = client.patch(
        "/api/documents/doc-1/status", json={"status": "superseded"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": "doc-1",
        "name": "Scoping deck",
        "status": "superseded",
    }
    assert received == [("doc-1", DocumentStatus.SUPERSEDED)]


def test_updating_document_status_passes_document_id_and_status_through():
    updated = document("doc-2", "Draft roadmap", DocumentStatus.GROUND_TRUTH)
    client, received = make_status_client(updated)

    client.patch("/api/documents/doc-2/status", json={"status": "ground truth"})

    assert received == [("doc-2", DocumentStatus.GROUND_TRUTH)]


def test_updating_document_status_to_hypothesis():
    updated = document("doc-3", "Draft roadmap", DocumentStatus.HYPOTHESIS)
    client, _ = make_status_client(updated)

    response = client.patch(
        "/api/documents/doc-3/status", json={"status": "hypothesis"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "hypothesis"


def test_updating_document_status_with_invalid_status_returns_422():
    client, received = make_status_client(
        document("doc-1", "Scoping deck", DocumentStatus.GROUND_TRUTH)
    )

    response = client.patch(
        "/api/documents/doc-1/status", json={"status": "not-a-real-status"}
    )

    assert response.status_code == 422
    assert received == []


def test_unknown_document_id_returns_404():
    client, _ = make_status_client(DocumentNotFoundError("doc-missing"))

    response = client.patch(
        "/api/documents/doc-missing/status", json={"status": "hypothesis"}
    )

    assert response.status_code == 404
