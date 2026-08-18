from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .errors import EngagementNotFoundError
from .models import DocumentStatus, EngagementDocument
from .router import build_engagement_documents_router


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
