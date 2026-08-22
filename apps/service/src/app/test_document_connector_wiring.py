"""Attaching a link must put a document's *text* where the compiler reads it.

The seam this covers is the one a unit test cannot: `fetch_body` existed,
`attach_document` existed, `extract_text` existed, and the wire between them
returned `""` from a dictionary nothing wrote to. Every module passed its own
tests while a linked SharePoint document contributed a filename and nothing
else, and the question bank came back empty for what looked like a missing
model.

So these drive the production composition root over a fake Microsoft, and
assert on what ends up in the fields the compiler and retrieval actually read.
"""

from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.engagement.documents.graph import HttpResponse
from app.modules.settings.models import DocumentSourceSettings, SecretKey
from app.modules.settings.store import InMemorySettingsStore

LINK = "https://acme.sharepoint.com/sites/proj/Shared%20Documents/Scoping.docx"
ONEDRIVE = "https://acme-my.sharepoint.com/personal/rw/Documents/Notes.docx"


def docx(paragraphs: list[str]) -> bytes:
    """A real .docx — the format a scoping deck actually arrives in."""
    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            f"<w:document {namespace}><w:body>{body}</w:body></w:document>",
        )
    return buffer.getvalue()


class FakeMicrosoft:
    def __init__(self, content: bytes, *, name: str = "Scoping.docx"):
        self.content = content
        self.name = name
        self.calls: list[str] = []

    async def __call__(self, method, url, *, headers=None, data=None):
        self.calls.append(url)
        if url.startswith("https://login.microsoftonline.com/"):
            return HttpResponse(
                status=200,
                body=json.dumps({"access_token": "tok", "expires_in": 3600}).encode(),
            )
        if url.endswith("/content"):
            return HttpResponse(status=200, body=self.content)
        return HttpResponse(status=200, body=json.dumps({"name": self.name}).encode())


def configured_store() -> InMemorySettingsStore:
    store = InMemorySettingsStore(read_environment=False)
    store.write_documents(DocumentSourceSettings(tenant_id="t-1", client_id="c-1"))
    store.set_secret(SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET, "shhh")
    return store


def client_for(transport, *, store=None) -> tuple[TestClient, Backend]:
    backend = Backend()
    app = build_app(
        backend,
        settings_store=store if store is not None else configured_store(),
        document_transport=transport,
    )
    return TestClient(app), backend


def an_engagement(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Logistics",
            "sector": "Freight",
            "commercial_context": "Fixed-price discovery",
        },
    )
    assert created.status_code == 201
    return created.json()["engagement_id"]


class TestALinkedDocumentReachesTheCompiler:
    def test_the_text_inside_the_document_is_stored_not_the_filename(self):
        transport = FakeMicrosoft(docx(["Throughput is 350 consignments a day."]))
        client, backend = client_for(transport)
        engagement = an_engagement(client)

        attached = client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        assert attached.status_code == 201
        stored = backend.document_texts[attached.json()["id"]]
        assert "Throughput is 350 consignments a day." in stored

    def test_the_document_is_indexed_the_way_an_uploaded_one_is(self):
        # An uploaded document is chunked and digested on arrival (FR-3.3). A
        # linked one landed in the list and in no index, so retrieval could
        # never surface it — the same document, invisible depending on which
        # way it came in.
        transport = FakeMicrosoft(docx(["Cross-dock runs two shifts."]))
        client, backend = client_for(transport)
        engagement = an_engagement(client)

        attached = client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        document_id = attached.json()["id"]
        assert backend.document_chunks.get(document_id)
        assert document_id in backend.context_pack_digests

    def test_it_still_appears_in_the_list_the_operator_reads(self):
        transport = FakeMicrosoft(docx(["x"]))
        client, _backend = client_for(transport)
        engagement = an_engagement(client)

        client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        listed = client.get(f"/api/engagements/{engagement}/documents")
        assert [d["name"] for d in listed.json()["documents"]] == ["Scoping.docx"]

    def test_a_onedrive_link_is_accepted_and_read(self):
        transport = FakeMicrosoft(docx(["Personal working notes."]), name="Notes.docx")
        client, backend = client_for(transport)
        engagement = an_engagement(client)

        attached = client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": ONEDRIVE, "status": "hypothesis"},
        )

        assert attached.status_code == 201
        assert "Personal working notes." in backend.document_texts[attached.json()["id"]]


class TestWhenTheConnectorCannotRead:
    def test_an_unconfigured_connector_refuses_the_link_and_says_why(self):
        # Silently attaching an empty document is what produced the empty bank.
        # Better to refuse the attach and name the missing setting.
        transport = FakeMicrosoft(docx(["x"]))
        client, _backend = client_for(
            transport, store=InMemorySettingsStore(read_environment=False)
        )
        engagement = an_engagement(client)

        attached = client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        assert attached.status_code == 502
        assert "not configured" in attached.json()["detail"].lower()

    def test_microsoft_refusing_the_credential_is_reported_verbatim(self):
        async def rejects(method, url, *, headers=None, data=None):
            if url.startswith("https://login.microsoftonline.com/"):
                return HttpResponse(
                    status=401,
                    body=json.dumps(
                        {"error_description": "AADSTS7000215: invalid client secret"}
                    ).encode(),
                )
            return HttpResponse(status=200, body=b"{}")

        client, _backend = client_for(rejects)
        engagement = an_engagement(client)

        attached = client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        assert attached.status_code == 502
        assert "AADSTS7000215" in attached.json()["detail"]

    def test_nothing_is_attached_when_the_fetch_fails(self):
        async def rejects(method, url, *, headers=None, data=None):
            return HttpResponse(status=403, body=json.dumps({"error": {"message": "no"}}).encode())

        client, _backend = client_for(rejects)
        engagement = an_engagement(client)

        client.post(
            f"/api/engagements/{engagement}/documents/link",
            json={"url": LINK, "status": "ground truth"},
        )

        listed = client.get(f"/api/engagements/{engagement}/documents")
        assert listed.json()["documents"] == []


class TestTheUploadPathStillWorks:
    def test_an_uploaded_docx_is_read_as_text_too(self):
        client, backend = client_for(FakeMicrosoft(b""))
        engagement = an_engagement(client)

        uploaded = client.post(
            f"/api/engagements/{engagement}/documents",
            files={"file": ("Scoping.docx", docx(["Uploaded body text."]), "application/octet-stream")},
            data={"status": "ground truth"},
        )

        assert uploaded.status_code == 201
        stored = backend.document_texts[uploaded.json()["document_id"]]
        assert "Uploaded body text." in stored
        assert "�" not in stored
