"""End-to-end test of the multi-meeting arc: requirements_state carries forward, and the
second meeting's bank weights toward the open questions the first meeting left open (PRD
FR-8.9, FR-4.8).

Meeting 1's debrief pipeline produces a `RequirementsCoverageMatrix` and a
`BmadArtifactSet` (with its own ranked `open_questions`); `merge_requirements_state_forward`
folds those into the engagement's standing `RequirementsState` (PRD FR-8.9) — this test
drives that merge directly, the same way `debrief/artifacts/test_state.py` does, since no
full debrief-session HTTP flow exists yet to produce a matrix and artifact set from a real
transcript. What this test adds beyond `test_state.py` is the second half of the arc: the
engagement's compiler recompiles meeting 2's bank from meeting 1's open questions (PRD
FR-4.8, `compiler/bank/recompile.py`), and this asserts that recompile through the real
`GET /api/meetings/{id}/bank` route, not just the pure function.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.compiler.bank.models import BankCandidate
from app.modules.compiler.bank.recompile import InheritedOpenQuestion
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    FillState,
    RequirementsCoverageMatrix,
)
from app.modules.debrief.artifacts.state import merge_requirements_state_forward
from app.modules.debrief.pipeline.models import (
    ArtifactCitation,
    BmadArtifactSet,
    ClaimProvenance,
    DecisionLogEntry,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
)
from fastapi.testclient import TestClient

from conftest import Backend

_MEETING_1_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_MEETING_2_AT = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _citation(quoted_text: str) -> ArtifactCitation:
    return ArtifactCitation(
        utterance_id="u1",
        session_id="meeting-1",
        start_seconds=0.0,
        end_seconds=1.0,
        speaker_tag="client",
        quoted_text=quoted_text,
        original_language="en",
    )


def _coverage_citation(quoted_text: str) -> CoverageCitation:
    return CoverageCitation(
        session_id="meeting-1",
        engine="engine-a",
        start_seconds=0.0,
        end_seconds=1.0,
        quoted_text=quoted_text,
        transcript_completed_at=_MEETING_1_AT,
    )


def _meeting_1_matrix() -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id="meeting-1",
        status=CoverageMatrixStatus.COMPLETE,
        entries=[
            CoverageMatrixEntry(
                section_key="timeline",
                title="Timeline",
                fill_state=FillState.FILLED,
                utterance_ids=["u1"],
                citations=[_coverage_citation("we ship in Q3")],
            ),
            CoverageMatrixEntry(
                section_key="budget",
                title="Budget",
                fill_state=FillState.EMPTY,
                utterance_ids=[],
                citations=[],
            ),
        ],
        is_fully_covered=False,
        generated_at=_MEETING_1_AT,
    )


def _meeting_1_artifacts() -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=[
            OpenQuestion(
                text="who owns budget sign-off?",
                impact_rank=1,
                provenance=ClaimProvenance.STATED,
                citations=[_citation("someone from finance needs to sign off")],
            ),
            OpenQuestion(
                text="which regions launch first?",
                impact_rank=2,
                provenance=ClaimProvenance.INFERRED,
                citations=[_citation("we'll probably roll out in phases")],
            ),
        ],
        decisions=[
            DecisionLogEntry(
                text="ship by Q3",
                decided_by="client",
                provenance=ClaimProvenance.STATED,
                citations=[_citation("we ship in Q3")],
            )
        ],
        project_brief=ProjectBriefDraft(body="brief", provenance=ClaimProvenance.STATED, citations=[]),
        follow_up_email=FollowUpEmailDraft(subject="Next steps", body="body", provenance=ClaimProvenance.STATED, citations=[]),
    )


def _meeting_2_matrix() -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id="meeting-2",
        status=CoverageMatrixStatus.COMPLETE,
        entries=[
            CoverageMatrixEntry(
                section_key="budget",
                title="Budget",
                fill_state=FillState.FILLED,
                utterance_ids=["u2"],
                citations=[_coverage_citation("budget is 50k")],
            ),
        ],
        is_fully_covered=False,
        generated_at=_MEETING_2_AT,
    )


def test_multi_meeting_arc_carries_requirements_state_forward_and_weights_the_next_bank(
    client: TestClient, backend: Backend
) -> None:
    engagement_id = "eng-1"

    meeting_1_state = asyncio.run(
        merge_requirements_state_forward(
            engagement_id,
            None,
            _meeting_1_matrix(),
            _meeting_1_artifacts(),
            lambda state: _save(backend, state),
            merged_at=_MEETING_1_AT,
        )
    )

    response = client.get(f"/api/engagements/{engagement_id}/requirements-state")
    assert response.status_code == 200
    assert [req["section_key"] for req in response.json()["confirmed_requirements"]] == ["timeline"]
    assert response.json()["decisions"][0]["text"] == "ship by Q3"

    meeting_2_state = asyncio.run(
        merge_requirements_state_forward(
            engagement_id,
            meeting_1_state,
            _meeting_2_matrix(),
            BmadArtifactSet(
                open_questions=[],
                decisions=[],
                project_brief=ProjectBriefDraft(body="brief 2", provenance=ClaimProvenance.STATED, citations=[]),
                follow_up_email=FollowUpEmailDraft(
                    subject="Next steps", body="body", provenance=ClaimProvenance.STATED, citations=[]
                ),
            ),
            lambda state: _save(backend, state),
            merged_at=_MEETING_2_AT,
        )
    )

    response = client.get(f"/api/engagements/{engagement_id}/requirements-state")
    assert response.status_code == 200
    section_keys = {req["section_key"] for req in response.json()["confirmed_requirements"]}
    assert section_keys == {"timeline", "budget"}, "meeting 1's confirmed requirement must still carry forward"

    backend.meeting_base_candidates["meeting-2"] = [
        BankCandidate(id="c-launch-plan", template_section="scope", phrasing="what is the launch plan?", priority=1)
    ]
    meeting_1_open_questions = sorted(_meeting_1_artifacts().open_questions, key=lambda q: q.impact_rank)
    backend.meeting_inherited_open_questions["meeting-2"] = [
        InheritedOpenQuestion(text=question.text, impact_rank=question.impact_rank)
        for question in meeting_1_open_questions
    ]

    bank_response = client.get("/api/meetings/meeting-2/bank")
    assert bank_response.status_code == 200
    candidates = bank_response.json()["candidates"]

    inherited = [c for c in candidates if c["inherited_from_open_question"]]
    assert [c["phrasing"] for c in inherited] == [
        "who owns budget sign-off?",
        "which regions launch first?",
    ], "second meeting bank must show meeting 1's open questions, ranked by impact"
    assert candidates[0]["phrasing"] == "who owns budget sign-off?", "highest-impact inherited question must lead the bank"
    assert candidates[-1]["id"] == "c-launch-plan", "freshly compiled candidates rank behind every inherited open question"

    assert meeting_2_state.updated_at == _MEETING_2_AT


async def _save(backend: Backend, state) -> None:
    backend.requirements_states[state.engagement_id] = state
