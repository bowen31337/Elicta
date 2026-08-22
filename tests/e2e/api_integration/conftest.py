"""Fixtures for the API integration suite.

The app assembly itself lives in `app.composition` — this suite drives the
production composition root rather than a copy of it, which is what keeps
the two from drifting apart.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.engagement.documents.graph import HttpResponse
from app.modules.settings.models import DocumentSourceSettings, SecretKey
from app.modules.settings.store import InMemorySettingsStore

__all__ = ["Backend", "build_app", "configured_settings_store", "fake_microsoft"]


def _docx(text: str) -> bytes:
    """A real `.docx`, so a linked document carries readable text.

    The suite used to attach links against a connector that returned `""` for
    everything, which meant every "the document is attached" assertion held for
    a document with no content in it. A link that cannot be read is now refused
    outright, so the fixture has to supply something a reader can actually open.
    """

    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            f"<w:document {namespace}><w:body><w:p><w:r><w:t>{text}"
            "</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


LINKED_DOCUMENT_TEXT = "Depot scheduling is rebuilt around consignment volume."


async def fake_microsoft(method, url, *, headers=None, data=None) -> HttpResponse:
    """Microsoft Graph, as far as this suite is concerned.

    Injected the same way the inference engines are: the point of the suite is
    the seams between this service's own parts, and a vendor round trip in the
    middle of that would test somebody else's uptime.
    """

    if url.startswith("https://login.microsoftonline.com/"):
        return HttpResponse(
            status=200,
            body=json.dumps({"access_token": "test-token", "expires_in": 3600}).encode(),
        )
    if url.endswith("/content"):
        return HttpResponse(status=200, body=_docx(LINKED_DOCUMENT_TEXT))
    return HttpResponse(
        status=200, body=json.dumps({"name": "depot-scope.docx"}).encode()
    )


def configured_settings_store() -> InMemorySettingsStore:
    """A store with the document connector configured.

    `read_environment=False` on purpose: a developer with `ELICTA_GRAPH_*` set
    for their own tenant must not have the suite quietly start reaching it.

    A plain function as well as a fixture, because a test module that builds
    its own app — there is one, for the compiler engines — needs the same store
    and cannot ask for a fixture from inside another fixture's argument list.
    """

    store = InMemorySettingsStore(read_environment=False)
    store.write_documents(
        DocumentSourceSettings(tenant_id="test-tenant", client_id="test-client")
    )
    store.set_secret(SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET, "test-secret")
    return store


@pytest.fixture
def settings_store() -> InMemorySettingsStore:
    return configured_settings_store()


@pytest.fixture
def backend() -> Backend:
    return Backend()


@pytest.fixture
def app(backend: Backend, settings_store: InMemorySettingsStore) -> FastAPI:
    return build_app(
        backend,
        settings_store=settings_store,
        document_transport=fake_microsoft,
    )


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
