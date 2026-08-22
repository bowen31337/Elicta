"""Editing the compiled bank: the operator's two corrections, over HTTP.

A compiled bank is the Analyst pass's opinion, and the operator is the one who
has met the client. Two edits exist for that: drop a question that does not
apply, and reword one that does. Both are keyed by candidate id across every
engagement's bank, so both have a "no such candidate" half — and answering 204
for an id nobody has would report a correction that never happened.

The compiler engines are faked, the way `test_compile_input_seam.py` fakes
them: the model's judgement is not what is under test. Everything else goes
through the API, including getting the candidates into the bank in the first
place.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
    BmadCandidateDraft,
)
from app.modules.compiler.citations.models import (
    ClaimStructuringOutput,
    DocumentExtractionOutput,
)
from app.orchestration.engines import CompilerEngines
from conftest import configured_settings_store, fake_microsoft

# PRD FR-4.1 requires a pass to produce 150-300 candidates; a pass outside
# that range is rejected as malformed, so a fixture has to be a real bank.
BANK_SIZE = 150


def _drafts() -> list[BmadCandidateDraft]:
    return [
        BmadCandidateDraft(
            template_section="performance",
            trigger_types=["vague_adjective"],
            phrasing=f"How fast is fast enough, in seconds, for step {index}?",
            stub=f"How fast, step {index}?",
            lang="en",
            priority=1,
        )
        for index in range(BANK_SIZE)
    ]


@pytest.fixture
def compiled_client() -> TestClient:
    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        return "batch-job-1"

    async def fetch_batch(batch_job_id: str) -> list[AnalystBatchResult]:
        # Attributed by `custom_id`, which is the engagement the request was
        # submitted under — never by position in the batch.
        return [
            AnalystBatchResult(
                custom_id="eng-1",
                output=BmadAnalystPassOutput(candidates=_drafts()),
            )
        ]

    return TestClient(
        build_app(
            Backend(),
            compiler_engines=CompilerEngines(
                name="claude-test",
                extract=extract,
                structure=structure,
                submit_batch=submit_batch,
                fetch_batch=fetch_batch,
            ),
            settings_store=configured_settings_store(),
            document_transport=fake_microsoft,
        )
    )


def _compiled_bank(client: TestClient) -> tuple[str, list[dict]]:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    assert created.status_code == 201, created.text
    engagement_id = created.json()["engagement_id"]

    compiled = client.post(f"/api/engagements/{engagement_id}/bank/compile")
    assert compiled.status_code == 202, compiled.text

    assert _bank_candidates(client, engagement_id), (
        "the compile put no bank where the endpoint reads"
    )
    return engagement_id, _bank_candidates(client, engagement_id)


def _bank_candidates(client: TestClient, engagement_id: str) -> list[dict]:
    """The bank flattened out of its per-section tree."""

    bank = client.get(f"/api/engagements/{engagement_id}/bank")
    assert bank.status_code == 200, bank.text
    return [
        candidate
        for section in bank.json()["sections"]
        for candidate in section["candidates"]
    ]


def test_a_compiled_candidate_can_be_dropped(compiled_client: TestClient) -> None:
    engagement_id, candidates = _compiled_bank(compiled_client)
    doomed = candidates[0]["id"]

    removed = compiled_client.delete(f"/api/bank/candidates/{doomed}")

    assert removed.status_code == 204, removed.text
    remaining = _bank_candidates(compiled_client, engagement_id)
    assert len(remaining) == BANK_SIZE - 1
    assert doomed not in {c["id"] for c in remaining}


def test_dropping_a_candidate_nobody_has_is_a_404_even_with_a_bank_present(
    compiled_client: TestClient,
) -> None:
    """The walk has to cross every engagement's bank before giving up.

    With a populated bank, a loop that returns on the first list it finishes
    would report a successful removal for an id that is not in any of them.
    """

    _compiled_bank(compiled_client)

    response = compiled_client.delete("/api/bank/candidates/no-such-candidate")

    assert response.status_code == 404


def test_a_compiled_candidate_can_be_reworded(compiled_client: TestClient) -> None:
    engagement_id, candidates = _compiled_bank(compiled_client)
    target = candidates[0]["id"]

    patched = compiled_client.patch(
        f"/api/bank/candidates/{target}",
        json={"phrasing": "What is the longest acceptable dwell time, in minutes?"},
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["phrasing"] == (
        "What is the longest acceptable dwell time, in minutes?"
    )

    stored = _bank_candidates(compiled_client, engagement_id)
    reworded = next(c for c in stored if c["id"] == target)
    assert reworded["phrasing"] == (
        "What is the longest acceptable dwell time, in minutes?"
    )
