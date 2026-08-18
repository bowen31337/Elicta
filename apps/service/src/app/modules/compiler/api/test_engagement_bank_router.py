"""Tests for the engagement-level compiled question bank HTTP surface (PRD FR-4.8).

Covers `GET /api/engagements/{id}/bank`: the engagement's compiled question
bank rendered as a reviewable tree grouped by `template_section`.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.compiler.api.models import BankCandidate
from app.modules.compiler.api.router import build_engagement_bank_router


def make_client(compiled_candidates: dict[str, list[BankCandidate]] | None = None) -> TestClient:
    compiled_candidates = compiled_candidates or {}

    async def get_compiled_candidates(engagement_id: str) -> list[BankCandidate]:
        return compiled_candidates.get(engagement_id, [])

    app = FastAPI()
    app.include_router(build_engagement_bank_router(get_compiled_candidates))
    return TestClient(app)


def test_get_engagement_bank_returns_200_grouped_by_template_section():
    client = make_client(
        compiled_candidates={
            "engagement-1": [
                BankCandidate(id="c-scope-1", template_section="scope", phrasing="What is out of scope?", priority=1),
                BankCandidate(id="c-scope-2", template_section="scope", phrasing="Which sites?", priority=2),
                BankCandidate(id="c-timeline-1", template_section="timeline", phrasing="When live?", priority=3),
            ]
        }
    )

    response = client.get("/api/engagements/engagement-1/bank")

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "engagement-1"
    sections = body["sections"]
    assert [s["template_section"] for s in sections] == ["scope", "timeline"]
    assert [c["id"] for c in sections[0]["candidates"]] == ["c-scope-1", "c-scope-2"]
    assert [c["id"] for c in sections[1]["candidates"]] == ["c-timeline-1"]


def test_get_engagement_bank_for_unknown_engagement_returns_200_with_an_empty_tree():
    client = make_client()

    response = client.get("/api/engagements/unknown/bank")

    assert response.status_code == 200
    assert response.json()["sections"] == []
