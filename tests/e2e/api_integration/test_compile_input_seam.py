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

import asyncio

import pytest
from app.composition import Backend, build_app
from app.modules.compiler.citations.models import (
    ClaimStructuringOutput,
    DocumentExtractionOutput,
)
from app.orchestration.engines import CompilerEngines
from conftest import configured_settings_store, fake_microsoft
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
    # The document connector is injected for the same reason the compiler
    # engines are: this suite tests the seams between this service's parts, and
    # a link that cannot be read is now refused rather than attached empty — so
    # a fixture with no connector would test the refusal, not the compile.
    return TestClient(
        build_app(
            Backend(),
            compiler_engines=engines,
            settings_store=configured_settings_store(),
            document_transport=fake_microsoft,
        )
    )


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


# ── The last hop: a compiled candidate reaching the bank ──────────────────


@pytest.fixture
def drafting_client() -> TestClient:
    """Compiler engines whose Analyst pass actually returns two questions.

    The other fixture in this module records what the stages were *given*. This
    one is about what comes back out: the chain ran to completion, wrote its
    analyst passes, and the bank endpoint still answered with nothing.
    """

    from app.modules.compiler.agent.models import (
        AnalystBatchResult,
        BmadAnalystPassOutput,
        BmadCandidateDraft,
    )

    def draft(section: str, phrasing: str, priority: int) -> BmadCandidateDraft:
        return BmadCandidateDraft(
            template_section=section,
            trigger_types=["vague_adjective"],
            phrasing=phrasing,
            stub=phrasing[:20],
            lang="en",
            priority=priority,
            requires=[],
            authority_match=[],
            source_doc=None,
        )

    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        return f"batch-{engagement_id}"

    async def fetch_batch(batch_job_id: str) -> list[Any]:
        engagement_id = batch_job_id.removeprefix("batch-")
        return [
            AnalystBatchResult(
                custom_id=engagement_id,
                output=BmadAnalystPassOutput(
                    # FR-4.1 requires a pass to produce 150-300 candidates, and
                    # the collector rejects a pass outside that range — so a
                    # two-question fixture is not a smaller version of a real
                    # pass, it is a failed one.
                    candidates=[
                        draft("Performance", "What does fast mean in seconds?", 1),
                        draft("Performance", "At median load or at peak?", 2),
                        *(
                            draft("Integrations", f"Filler question {n}?", n + 3)
                            for n in range(148)
                        ),
                    ]
                ),
            )
        ]

    engines = CompilerEngines(
        name="claude-test",
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
    )
    return TestClient(
        build_app(
            Backend(),
            compiler_engines=engines,
            settings_store=configured_settings_store(),
            document_transport=fake_microsoft,
        )
    )


def test_a_compiled_candidate_reaches_the_engagement_bank(
    drafting_client: TestClient,
) -> None:
    """The compile chain's output has to land where the bank endpoint reads.

    Everything up to here worked: documents were read, the context pack was
    built, the Analyst batch was submitted and collected, and the run reported
    every stage complete. The candidates went to `analyst_passes` and the bank
    endpoint reads `compiled_candidates`, so `GET .../bank` answered `[]` — the
    same write/read split that made a linked document vanish after a 201, one
    stage further along.
    """

    engagement_id, _document_id = _engagement_with_an_uploaded_document(drafting_client)

    triggered = drafting_client.post(f"/api/engagements/{engagement_id}/bank/compile")
    assert triggered.status_code == 202, triggered.text

    bank = drafting_client.get(f"/api/engagements/{engagement_id}/bank")
    assert bank.status_code == 200, bank.text
    sections = bank.json()["sections"]

    assert sections, f"the compile produced no bank: {bank.text}"
    phrasings = [c["phrasing"] for s in sections for c in s["candidates"]]
    assert phrasings[:2] == [
        "What does fast mean in seconds?",
        "At median load or at peak?",
    ]
    assert len(phrasings) == 150


def test_a_compiled_candidate_can_then_be_pruned(drafting_client: TestClient) -> None:
    """Journey 1's reviewing step needs the ids the compile minted to be real."""

    engagement_id, _document_id = _engagement_with_an_uploaded_document(drafting_client)
    drafting_client.post(f"/api/engagements/{engagement_id}/bank/compile")

    bank = drafting_client.get(f"/api/engagements/{engagement_id}/bank").json()
    first = bank["sections"][0]["candidates"][0]["id"]

    pruned = drafting_client.patch(f"/api/bank/candidates/{first}", json={"pruned": True})
    assert pruned.status_code == 200, pruned.text
    assert pruned.json()["pruned"] is True


# ── The bank filling, which needs a second visit to the batch ─────────────


def _drafts(count: int = 150):
    from app.modules.compiler.agent.models import BmadCandidateDraft

    return [
        BmadCandidateDraft(
            template_section="Performance" if n % 2 else "Integrations",
            trigger_types=["vague_adjective"],
            phrasing=f"Question {n}?",
            stub=f"stub {n}",
            lang="en",
            priority=n + 1,
            requires=[],
            authority_match=[],
            source_doc=None,
        )
        for n in range(count)
    ]


class _Batch:
    """A batch that is not ready until it is — like every real one."""

    def __init__(self) -> None:
        self.ready = False
        self.fetches = 0

    async def submit(self, engagement_id: str, context_pack) -> str:
        return f"batch-{engagement_id}"

    async def fetch(self, batch_job_id: str):
        from app.modules.compiler.agent.models import (
            AnalystBatchResult,
            BmadAnalystPassOutput,
        )

        self.fetches += 1
        if not self.ready:
            return []
        return [
            AnalystBatchResult(
                custom_id=batch_job_id.removeprefix("batch-"),
                output=BmadAnalystPassOutput(candidates=_drafts()),
            )
        ]


@pytest.fixture
def batch() -> _Batch:
    return _Batch()


@pytest.fixture
def slow_batch_app(batch: _Batch):
    """The production root over a batch that finishes later, as they do."""

    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        return ClaimStructuringOutput(candidates=[])

    engines = CompilerEngines(
        name="claude-test",
        extract=extract,
        structure=structure,
        submit_batch=batch.submit,
        fetch_batch=batch.fetch,
    )
    backend = Backend()
    app = build_app(
        backend,
        compiler_engines=engines,
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    return app, backend, engines


def test_the_bank_fills_once_the_batch_has_been_collected(slow_batch_app, batch) -> None:
    """The whole point, end to end.

    Compiling submits a batch that is not ready, and the bank is empty — which
    is correct and is where it used to stay for ever. Once the batch ends, a
    sweep collects it and the questions are on the screen.
    """

    from app.composition import build_bank_collector

    app, backend, engines = slow_batch_app
    client = TestClient(app)
    engagement_id, _document_id = _engagement_with_an_uploaded_document(client)

    assert client.post(f"/api/engagements/{engagement_id}/bank/compile").status_code == 202
    assert client.get(f"/api/engagements/{engagement_id}/bank").json()["sections"] == []

    batch.ready = True
    outcomes = asyncio.run(build_bank_collector(backend, engines).sweep())

    assert [o.state.value for o in outcomes] == ["collected"], outcomes
    sections = client.get(f"/api/engagements/{engagement_id}/bank").json()["sections"]
    assert sections, "the bank is still empty after the batch was collected"
    assert sum(len(s["candidates"]) for s in sections) == 150


def test_a_sweep_before_the_batch_ends_leaves_the_bank_alone(slow_batch_app) -> None:
    from app.composition import build_bank_collector

    app, backend, engines = slow_batch_app
    client = TestClient(app)
    engagement_id, _document_id = _engagement_with_an_uploaded_document(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    outcomes = asyncio.run(build_bank_collector(backend, engines).sweep())

    assert [o.state.value for o in outcomes] == ["pending"]
    assert client.get(f"/api/engagements/{engagement_id}/bank").json()["sections"] == []


def test_a_collected_bank_is_not_collected_twice(slow_batch_app, batch) -> None:
    """Sweeping again must not append a second copy of every question."""

    from app.composition import build_bank_collector

    app, backend, engines = slow_batch_app
    client = TestClient(app)
    engagement_id, _document_id = _engagement_with_an_uploaded_document(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")
    batch.ready = True

    collector = build_bank_collector(backend, engines)
    asyncio.run(collector.sweep())
    fetches_after_first = batch.fetches
    assert asyncio.run(collector.sweep()) == []

    sections = client.get(f"/api/engagements/{engagement_id}/bank").json()["sections"]
    assert sum(len(s["candidates"]) for s in sections) == 150
    assert batch.fetches == fetches_after_first, "the provider was asked again"
