"""The seeded-body shortcut on the link-attachment path.

`fetch_body` consults `reference_document_bodies` before it consults Microsoft,
and only before: a test that wants to exercise the *attach* path — what the
document becomes once its text is in hand — should not need a tenant, and must
not make a request to get one.

The property worth pinning is the "and only first" half. A shortcut that still
called Graph would make every such test depend on somebody else's uptime; one
that were consulted after the fetch would never be used at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.engagement.documents.graph import HttpResponse
from conftest import configured_settings_store

SHAREPOINT_URL = "https://contoso.sharepoint.com/sites/logistics/Shared%20Documents/scope.docx"
SEEDED_TEXT = "Depots confirm each driver roster by phone the evening before."


@pytest.fixture
def refusing_transport():
    """A connector that fails the test if it is reached at all."""

    calls: list[str] = []

    async def transport(method, url, *, headers=None, data=None) -> HttpResponse:
        calls.append(url)
        return HttpResponse(status=500, body=b"the seeded body should have been used")

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def test_a_seeded_body_is_used_without_calling_microsoft(refusing_transport) -> None:
    client = TestClient(
        build_app(
            # Configuration the app is built with, not a read being stood in
            # for: this is the affordance's own input.
            Backend(reference_document_bodies={SHAREPOINT_URL: SEEDED_TEXT}),
            settings_store=configured_settings_store(),
            document_transport=refusing_transport,
        )
    )
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    engagement_id = created.json()["engagement_id"]

    attached = client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": SHAREPOINT_URL, "status": "hypothesis"},
    )

    assert attached.status_code == 201, attached.text
    assert refusing_transport.calls == [], "the seeded body still went to Microsoft"


def test_the_seeded_text_is_what_reaches_retrieval(refusing_transport) -> None:
    """A document in the list and in no index is invisible to the compiler.

    Attaching has to end in indexed text, whichever intake path supplied it.
    """

    backend = Backend(reference_document_bodies={SHAREPOINT_URL: SEEDED_TEXT})
    client = TestClient(
        build_app(
            backend,
            settings_store=configured_settings_store(),
            document_transport=refusing_transport,
        )
    )
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    engagement_id = created.json()["engagement_id"]

    attached = client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": SHAREPOINT_URL, "status": "hypothesis"},
    )
    assert attached.status_code == 201, attached.text

    document_id = attached.json()["id"]
    assert backend.document_texts.get(document_id) == SEEDED_TEXT
