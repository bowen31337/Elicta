"""Tests for the per-meeting recompiled question bank HTTP surface (PRD FR-4.8)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.compiler.api.models import BankCandidate
from app.modules.compiler.api.recompile import InheritedOpenQuestion
from app.modules.compiler.api.router import build_meeting_bank_router


def make_client(
    base_candidates: dict[str, list[BankCandidate]] | None = None,
    inherited_open_questions: dict[str, list[InheritedOpenQuestion]] | None = None,
) -> TestClient:
    base_candidates = base_candidates or {}
    inherited_open_questions = inherited_open_questions or {}

    async def get_base_candidates(meeting_id: str) -> list[BankCandidate]:
        return base_candidates.get(meeting_id, [])

    async def get_inherited_open_questions(meeting_id: str) -> list[InheritedOpenQuestion]:
        return inherited_open_questions.get(meeting_id, [])

    app = FastAPI()
    app.include_router(build_meeting_bank_router(get_base_candidates, get_inherited_open_questions))
    return TestClient(app)


def test_get_meeting_bank_returns_200_with_base_candidates_when_nothing_is_inherited():
    client = make_client(
        base_candidates={"meeting-1": [BankCandidate(id="c1", template_section="scope", phrasing="c1", priority=1)]}
    )

    response = client.get("/api/meetings/meeting-1/bank")

    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert [c["id"] for c in body["candidates"]] == ["c1"]


def test_get_meeting_bank_weights_toward_inherited_open_questions():
    client = make_client(
        base_candidates={"meeting-2": [BankCandidate(id="c1", template_section="scope", phrasing="c1", priority=1)]},
        inherited_open_questions={
            "meeting-2": [InheritedOpenQuestion(text="who owns budget sign-off?", impact_rank=1)]
        },
    )

    response = client.get("/api/meetings/meeting-2/bank")

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates[0]["phrasing"] == "who owns budget sign-off?"
    assert candidates[0]["inherited_from_open_question"] is True
    assert candidates[1]["id"] == "c1"


def test_get_meeting_bank_for_unknown_meeting_returns_200_with_an_empty_bank():
    client = make_client()

    response = client.get("/api/meetings/unknown/bank")

    assert response.status_code == 200
    assert response.json()["candidates"] == []
