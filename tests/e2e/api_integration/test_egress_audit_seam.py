"""The egress audit records what left the machine.

The defect this covers: `backend.egress_rows` was read by
`GET /api/audit/egress` and written by nothing, so the audit answered with an
empty list after real model calls. NFR-2.7 asks for a single audited
chokepoint; what existed was a chokepoint with nothing routed through it.

The engines are faked, so nothing actually leaves the machine here — what is
under test is that a call *through the inference seam* is audited, which is
the boundary every real vendor call crosses.
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

FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01, comfortably after any test run


def _engines(*, fail: bool = False) -> CompilerEngines:
    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        if fail:
            raise RuntimeError("the vendor rejected the request")
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        return "batch-job-1"

    async def fetch_batch(batch_job_id: str) -> list[Any]:
        return []

    return CompilerEngines(
        name="claude-test",
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
    )


@pytest.fixture
def compiling_client() -> TestClient:
    return TestClient(build_app(Backend(), compiler_engines=_engines()))


def _engagement(client: TestClient) -> str:
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


def _audit(client: TestClient, engagement_id: str, start_ms: int = 0, end_ms: int = FAR_FUTURE_MS):
    return client.get(
        "/api/audit/egress",
        params={"engagement_id": engagement_id, "start_ms": start_ms, "end_ms": end_ms},
    )


def test_a_call_through_the_inference_seam_is_audited(compiling_client: TestClient) -> None:
    engagement_id = _engagement(compiling_client)
    assert _audit(compiling_client, engagement_id).json() == []

    compiled = compiling_client.post(f"/api/engagements/{engagement_id}/bank/compile")
    assert compiled.status_code == 202, compiled.text

    response = _audit(compiling_client, engagement_id)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "the compile made model calls and the audit shows none of them"
    row = rows[0]
    assert row["engagement_id"] == engagement_id
    assert row["processor_name"], "a row that does not name who was called is not an audit"
    assert row["timestamp_ms"] > 0
    assert row["success"] is True


def test_the_audit_window_is_honoured(compiling_client: TestClient) -> None:
    engagement_id = _engagement(compiling_client)
    compiling_client.post(f"/api/engagements/{engagement_id}/bank/compile")

    inside = _audit(compiling_client, engagement_id).json()
    assert inside

    outside = _audit(compiling_client, engagement_id, start_ms=1, end_ms=2).json()
    assert outside == [], "a window excluding the call still returned it"


def test_another_engagements_calls_are_not_in_this_ones_audit(
    compiling_client: TestClient,
) -> None:
    first = _engagement(compiling_client)
    second = _engagement(compiling_client)

    compiling_client.post(f"/api/engagements/{first}/bank/compile")

    assert _audit(compiling_client, first).json()
    assert _audit(compiling_client, second).json() == []


def test_a_failed_call_is_audited_too() -> None:
    """A call that failed still left the machine — the audit must show it."""

    client = TestClient(build_app(Backend(), compiler_engines=_engines(fail=True)))
    engagement_id = _engagement(client)

    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    rows = _audit(client, engagement_id).json()
    assert rows, "a failed vendor call left no audit row"
    assert rows[0]["success"] is False
    assert "vendor rejected" in rows[0]["error"]
