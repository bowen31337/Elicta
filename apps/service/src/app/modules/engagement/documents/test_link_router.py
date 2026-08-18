"""Tests for attaching a reference document by SharePoint/Teams link (PRD FR-3.2)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .errors import EngagementNotFoundError, ReferenceDocumentFetchError
from .models import DocumentLinkAttachmentRequest, DocumentStatus, ReferenceDocument
from .router import build_reference_document_link_router


def make_client(
    fetch_result: str | Exception,
    attach_result: ReferenceDocument | Exception | None = None,
) -> tuple[TestClient, list[str], list[tuple[str, DocumentLinkAttachmentRequest, str]]]:
    fetch_calls: list[str] = []
    attach_calls: list[tuple[str, DocumentLinkAttachmentRequest, str]] = []

    async def fetch_body(url: str) -> str:
        fetch_calls.append(url)
        if isinstance(fetch_result, Exception):
            raise fetch_result
        return fetch_result

    async def attach_document(
        engagement_id: str, payload: DocumentLinkAttachmentRequest, body: str
    ) -> ReferenceDocument:
        attach_calls.append((engagement_id, payload, body))
        if isinstance(attach_result, Exception):
            raise attach_result
        assert attach_result is not None
        return attach_result

    app = FastAPI()
    app.include_router(build_reference_document_link_router(fetch_body, attach_document))
    return TestClient(app), fetch_calls, attach_calls


def test_attaching_sharepoint_link_returns_201_with_persisted_document():
    persisted = ReferenceDocument(
        id="doc-1",
        engagement_id="eng-1",
        status=DocumentStatus.GROUND_TRUTH,
        source_uri="https://acme.sharepoint.com/sites/proj/scoping.docx",
    )
    client, fetch_calls, attach_calls = make_client("<the fetched body>", persisted)

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/scoping.docx",
            "status": "ground truth",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": "doc-1",
        "engagement_id": "eng-1",
        "status": "ground truth",
        "source_uri": "https://acme.sharepoint.com/sites/proj/scoping.docx",
    }
    assert fetch_calls == ["https://acme.sharepoint.com/sites/proj/scoping.docx"]
    assert len(attach_calls) == 1
    engagement_id, payload, body = attach_calls[0]
    assert engagement_id == "eng-1"
    assert payload.url == "https://acme.sharepoint.com/sites/proj/scoping.docx"
    assert payload.status == DocumentStatus.GROUND_TRUTH
    assert body == "<the fetched body>"


def test_attaching_teams_link_returns_201():
    persisted = ReferenceDocument(
        id="doc-2",
        engagement_id="eng-1",
        status=DocumentStatus.HYPOTHESIS,
        source_uri="https://teams.microsoft.com/l/file/abc123",
    )
    client, _, _ = make_client("body", persisted)

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={"url": "https://teams.microsoft.com/l/file/abc123", "status": "hypothesis"},
    )

    assert response.status_code == 201
    assert response.json()["source_uri"] == "https://teams.microsoft.com/l/file/abc123"


def test_fetch_happens_before_attach():
    client, fetch_calls, attach_calls = make_client(
        ReferenceDocumentFetchError("unreachable")
    )

    client.post(
        "/api/engagements/eng-1/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/scoping.docx",
            "status": "ground truth",
        },
    )

    assert fetch_calls == ["https://acme.sharepoint.com/sites/proj/scoping.docx"]
    assert attach_calls == []


def test_fetch_failure_returns_502_and_never_attaches():
    client, _, attach_calls = make_client(ReferenceDocumentFetchError("403 from graph api"))

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/scoping.docx",
            "status": "ground truth",
        },
    )

    assert response.status_code == 502
    assert attach_calls == []


def test_unknown_engagement_returns_404():
    client, _, _ = make_client("body", EngagementNotFoundError("eng-missing"))

    response = client.post(
        "/api/engagements/eng-missing/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/scoping.docx",
            "status": "ground truth",
        },
    )

    assert response.status_code == 404


def test_non_sharepoint_non_teams_link_returns_422_naming_the_field():
    client, fetch_calls, attach_calls = make_client(
        Exception("should not be called"), Exception("should not be called")
    )

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={"url": "https://dropbox.com/s/abc/scoping.docx", "status": "ground truth"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "url" for error in detail)
    assert fetch_calls == []
    assert attach_calls == []


def test_link_missing_scheme_returns_422():
    client, fetch_calls, _ = make_client(Exception("should not be called"))

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={"url": "acme.sharepoint.com/sites/proj/scoping.docx", "status": "ground truth"},
    )

    assert response.status_code == 422
    assert fetch_calls == []


def test_missing_status_returns_422_naming_the_field():
    client, fetch_calls, attach_calls = make_client(Exception("should not be called"))

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={"url": "https://acme.sharepoint.com/sites/proj/scoping.docx"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "status" for error in detail)
    assert fetch_calls == []
    assert attach_calls == []


def test_extra_field_is_rejected():
    client, _, _ = make_client("body", Exception("should not be called"))

    response = client.post(
        "/api/engagements/eng-1/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/scoping.docx",
            "status": "ground truth",
            "name": "not allowed here",
        },
    )

    assert response.status_code == 422
