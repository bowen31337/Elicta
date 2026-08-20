"""A document attached by link appears in the engagement's document list.

The defect this covers: the link endpoint wrote `backend.reference_documents`
while the list endpoint read `backend.engagement_documents`. A SharePoint
document could be attached, acknowledged with a `reference-document-N` id, and
never appear anywhere an operator looks. FR-3.2 names link attachment as an
intake path — an intake path that lands somewhere nothing reads is not one.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

SHAREPOINT_URL = (
    "https://contoso.sharepoint.com/sites/logistics/Shared%20Documents/depot-scope.docx"
)


def _create_engagement(client: TestClient) -> str:
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["engagement_id"]


def _list_documents(client: TestClient, engagement_id: str) -> list[dict]:
    response = client.get(f"/api/engagements/{engagement_id}/documents")
    assert response.status_code == 200, response.text
    return response.json()["documents"]


def test_a_linked_document_appears_in_the_document_list(client: TestClient) -> None:
    engagement_id = _create_engagement(client)

    attached = client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": SHAREPOINT_URL, "status": "ground truth"},
    )
    assert attached.status_code == 201, attached.text

    documents = _list_documents(client, engagement_id)
    assert len(documents) == 1, f"the attached document is not in the list: {documents}"
    assert documents[0]["status"] == "ground truth"
    assert documents[0]["document_id"] == attached.json()["id"]


def test_uploaded_and_linked_documents_share_one_list(client: TestClient) -> None:
    engagement_id = _create_engagement(client)

    uploaded = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("current-process.md", b"# Current depot process", "text/markdown")},
        data={"status": "ground truth"},
    )
    assert uploaded.status_code == 201, uploaded.text

    client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": SHAREPOINT_URL, "status": "hypothesis"},
    )

    documents = _list_documents(client, engagement_id)
    assert len(documents) == 2, documents
    assert {d["status"] for d in documents} == {"ground truth", "hypothesis"}
    assert len({d["document_id"] for d in documents}) == 2, "document ids collide"


def test_a_link_to_another_host_is_still_rejected(client: TestClient) -> None:
    """FR-3.2 asks for SharePoint and Teams specifically; the validation stands."""

    engagement_id = _create_engagement(client)

    rejected = client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": "https://drive.google.com/file/d/abc/view", "status": "ground truth"},
    )

    assert rejected.status_code == 422, rejected.text
    assert _list_documents(client, engagement_id) == []


def test_a_link_on_an_unknown_engagement_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/engagements/eng-missing/documents/link",
        json={"url": SHAREPOINT_URL, "status": "ground truth"},
    )

    assert response.status_code == 404, response.text
