"""Tests for the full PRD generation HTTP surface, gated on cross-meeting coverage (PRD FR-8.10)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.debrief.artifacts.models import (
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
)
from app.modules.debrief.artifacts.router import build_full_prd_router
from app.modules.debrief.pipeline.models import BmadArtifactSet, ClaimProvenance, FillState, FollowUpEmailDraft, ProjectBriefDraft
from fastapi import FastAPI
from fastapi.testclient import TestClient

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_entry(section_key: str, title: str, fill_state: FillState) -> CoverageMatrixEntry:
    return CoverageMatrixEntry(section_key=section_key, title=title, fill_state=fill_state, utterance_ids=[], citations=[])


def make_matrix(
    entries: list[CoverageMatrixEntry], *, status: CoverageMatrixStatus = CoverageMatrixStatus.COMPLETE,
    session_id: str = "session-1",
) -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id=session_id,
        status=status,
        entries=entries,
        is_fully_covered=bool(entries) and all(entry.fill_state == FillState.FILLED for entry in entries),
        generated_at=FIXED,
    )


def make_artifact_set() -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=[],
        decisions=[],
        project_brief=ProjectBriefDraft(body="draft brief", provenance=ClaimProvenance.STATED, citations=[]),
        follow_up_email=FollowUpEmailDraft(
            subject="Follow up", body="draft email", provenance=ClaimProvenance.STATED, citations=[]
        ),
    )


def make_client(
    matrices: list[RequirementsCoverageMatrix], *, threshold: float | None = None
) -> tuple[TestClient, list[str]]:
    generate_calls: list[str] = []

    async def get_matrices(engagement_id: str) -> list[RequirementsCoverageMatrix]:
        return matrices

    async def generate(engagement_id: str) -> BmadArtifactSet:
        generate_calls.append(engagement_id)
        return make_artifact_set()

    app = FastAPI()
    kwargs = {} if threshold is None else {"threshold": threshold}
    app.include_router(build_full_prd_router(get_matrices, generate, **kwargs))
    return TestClient(app), generate_calls


def test_full_coverage_across_meetings_generates_the_full_prd():
    matrices = [
        make_matrix([make_entry("timeline", "Timeline", FillState.FILLED)], session_id="meeting-1"),
        make_matrix([make_entry("budget", "Budget", FillState.FILLED)], session_id="meeting-2"),
    ]
    client, generate_calls = make_client(matrices)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 201
    assert generate_calls == ["eng-1"]
    assert response.json()["project_brief"]["body"] == "draft brief"


def test_insufficient_coverage_across_meetings_returns_409_with_an_explanation():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)]
        ),
    ]
    client, generate_calls = make_client(matrices)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 409
    assert "Budget" in response.json()["detail"]
    assert generate_calls == []


def test_an_engagement_with_no_meetings_at_all_returns_409():
    client, generate_calls = make_client([])

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 409
    assert generate_calls == []


def test_a_lower_custom_threshold_allows_generation_with_partial_coverage():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)]
        ),
    ]
    client, generate_calls = make_client(matrices, threshold=0.5)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 201
    assert generate_calls == ["eng-1"]
