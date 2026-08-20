"""The context compiler reads document text, not filenames.

The defect this covers: `_run_engagement_compile` built its extraction input
as `ExtractionSourceDocument(document_id=..., text=document.name)` — the
document's *filename* — and its analyst context pack with `documents=[]`
hardcoded. The compiler dutifully ran, extracted claims from the string
"current-process.md", and the bank stayed empty. That is why POST
/bank/compile returned a job id and nothing appeared to review.

The engines are faked here so the test can see what reached the extraction
stage. Faking the model is not the same as hand-placing state: every document
in this test is put there through the API.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.composition import Backend, build_app
from app.modules.compiler.citations.models import (
    ClaimStructuringOutput,
    DocumentExtractionOutput,
)
from app.orchestration.engines import CompilerEngines
from fastapi.testclient import TestClient

DOCUMENT_TEXT = (
    "Depots currently confirm each driver roster by phone the evening before. "
    "Rosters are final at 18:00 and changes after that are handled ad hoc."
)
SHAREPOINT_URL = "https://contoso.sharepoint.com/sites/logistics/Shared%20Documents/scope.docx"


class RecordedCompile:
    """What each faked compiler stage was handed."""

    def __init__(self) -> None:
        self.extraction_documents: list[Any] = []
        self.context_packs: list[Any] = []


@pytest.fixture
def recorded() -> RecordedCompile:
    return RecordedCompile()


@pytest.fixture
def compiling_client(recorded: RecordedCompile) -> TestClient:
    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        recorded.extraction_documents = list(documents)
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        recorded.context_packs.append(context_pack)
        return "batch-job-1"

    async def fetch_batch(batch_job_id: str) -> list[Any]:
        return []

    engines = CompilerEngines(
        name="claude-test",
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
    )
    return TestClient(build_app(Backend(), compiler_engines=engines))


def _engagement_with_an_uploaded_document(client: TestClient) -> tuple[str, str]:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    assert engagement.status_code == 201, engagement.text
    engagement_id = engagement.json()["engagement_id"]

    uploaded = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("current-process.md", DOCUMENT_TEXT.encode(), "text/markdown")},
        data={"status": "ground truth"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return engagement_id, uploaded.json()["document_id"]


def test_the_extraction_stage_is_handed_the_document_text(
    compiling_client: TestClient, recorded: RecordedCompile
) -> None:
    engagement_id, document_id = _engagement_with_an_uploaded_document(compiling_client)

    compiled = compiling_client.post(f"/api/engagements/{engagement_id}/bank/compile")
    assert compiled.status_code == 202, compiled.text

    assert recorded.extraction_documents, "the extraction stage was never reached"
    texts = {d.document_id: d.text for d in recorded.extraction_documents}
    assert document_id in texts
    assert "confirm each driver roster by phone" in texts[document_id]
    assert texts[document_id] != "current-process.md", "the compiler read the filename"


def test_the_analyst_context_pack_carries_the_documents(
    compiling_client: TestClient, recorded: RecordedCompile
) -> None:
    engagement_id, document_id = _engagement_with_an_uploaded_document(compiling_client)

    compiling_client.post(f"/api/engagements/{engagement_id}/bank/compile")

    assert recorded.context_packs, "the analyst batch was never submitted"
    pack = recorded.context_packs[-1]
    assert [d.document_id for d in pack.documents] == [document_id]
    assert "roster" in pack.documents[0].text
    assert pack.documents[0].status.value == "ground truth"


def test_a_linked_document_reaches_the_compiler_too(
    compiling_client: TestClient, recorded: RecordedCompile
) -> None:
    """FR-3.2's second intake path feeds the same compile, not a separate one."""

    engagement_id, document_id = _engagement_with_an_uploaded_document(compiling_client)
    attached = compiling_client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={"url": SHAREPOINT_URL, "status": "hypothesis"},
    )
    assert attached.status_code == 201, attached.text

    compiling_client.post(f"/api/engagements/{engagement_id}/bank/compile")

    reached = {d.document_id for d in recorded.extraction_documents}
    assert reached == {document_id, attached.json()["id"]}
