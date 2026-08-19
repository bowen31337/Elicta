"""Tests for merging one meeting's requirements state forward into the engagement's standing state (PRD FR-8.9)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.artifacts.models import (
    ConfirmedRequirement,
    CoverageCitation,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
    RequirementsState,
)
from app.modules.debrief.artifacts.state import merge_requirements_state_forward
from app.modules.debrief.pipeline.models import (
    ArtifactCitation,
    BmadArtifactSet,
    ClaimProvenance,
    DecisionLogEntry,
    FillState,
    FollowUpEmailDraft,
    ProjectBriefDraft,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_citation(quoted_text: str = "quoted", session_id: str = "session-1") -> CoverageCitation:
    return CoverageCitation(
        session_id=session_id,
        engine="record-path-engine",
        start_seconds=0.0,
        end_seconds=1.0,
        quoted_text=quoted_text,
        transcript_completed_at=FIXED,
    )


def make_confirmed_requirement(section_key: str, quoted_text: str) -> ConfirmedRequirement:
    return ConfirmedRequirement(
        section_key=section_key, title=section_key.title(), citations=[make_citation(quoted_text)]
    )


def make_entry(
    section_key: str, title: str, fill_state: FillState, *, citations: list[CoverageCitation] | None = None
) -> CoverageMatrixEntry:
    return CoverageMatrixEntry(
        section_key=section_key, title=title, fill_state=fill_state, utterance_ids=[], citations=citations or [],
    )


def make_matrix(
    entries: list[CoverageMatrixEntry], *, status: CoverageMatrixStatus = CoverageMatrixStatus.COMPLETE,
    session_id: str = "session-1", error: str | None = None,
) -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id=session_id, status=status, entries=entries, is_fully_covered=False, generated_at=FIXED,
        error=error,
    )


def make_artifact_citation(utterance_id: str = "utt-1") -> ArtifactCitation:
    return ArtifactCitation(
        utterance_id=utterance_id, session_id="session-1", start_seconds=0.0, end_seconds=1.0,
        speaker_tag="alice", quoted_text="quoted", original_language="en",
    )


def make_decision(text: str = "decided X", provenance: ClaimProvenance = ClaimProvenance.STATED) -> DecisionLogEntry:
    return DecisionLogEntry(
        text=text, decided_by="alice", provenance=provenance, citations=[make_artifact_citation()],
    )


def make_artifacts(decisions: list[DecisionLogEntry] | None = None) -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=[],
        decisions=decisions if decisions is not None else [],
        project_brief=ProjectBriefDraft(body="brief", provenance=ClaimProvenance.STATED, citations=[]),
        follow_up_email=FollowUpEmailDraft(
            subject="subject", body="body", provenance=ClaimProvenance.STATED, citations=[],
        ),
    )


def make_state(
    *, confirmed_requirements: list[ConfirmedRequirement] | None = None, decisions: list[DecisionLogEntry] | None = None,
) -> RequirementsState:
    return RequirementsState(
        engagement_id="engagement-1",
        confirmed_requirements=confirmed_requirements or [],
        contradictions=[],
        decisions=decisions or [],
        updated_at=FIXED,
    )


def test_a_first_meeting_with_no_previous_state_persists_a_fresh_state_from_its_own_matrix_and_decisions():
    saved: list[RequirementsState] = []

    async def save(state: RequirementsState) -> None:
        saved.append(state)

    matrix = make_matrix(
        [
            make_entry("timeline", "Timeline", FillState.FILLED, citations=[make_citation("we ship in Q3")]),
            make_entry("budget", "Budget", FillState.EMPTY),
        ]
    )
    artifacts = make_artifacts(decisions=[make_decision("go with vendor A")])

    result = asyncio.run(
        merge_requirements_state_forward("engagement-1", None, matrix, artifacts, save, merged_at=FIXED)
    )

    assert result.engagement_id == "engagement-1"
    assert [req.section_key for req in result.confirmed_requirements] == ["timeline"]
    assert result.contradictions == []
    assert [decision.text for decision in result.decisions] == ["go with vendor A"]
    assert result.updated_at == FIXED
    assert saved == [result]


def test_a_later_meeting_confirming_a_new_section_adds_it_to_the_carried_forward_state():
    async def save(state: RequirementsState) -> None:
        pass

    previous_state = make_state(decisions=[make_decision("go with vendor A")])
    matrix = make_matrix([make_entry("budget", "Budget", FillState.FILLED, citations=[make_citation("50k budget")])])
    artifacts = make_artifacts(decisions=[make_decision("set budget at 50k")])

    result = asyncio.run(
        merge_requirements_state_forward("engagement-1", previous_state, matrix, artifacts, save, merged_at=FIXED)
    )

    section_keys = {req.section_key for req in result.confirmed_requirements}
    assert section_keys == {"budget"}
    assert [decision.text for decision in result.decisions] == ["go with vendor A", "set budget at 50k"]
    assert result.contradictions == []


def test_reconfirming_a_section_with_the_same_quoted_citation_is_not_a_contradiction():
    async def save(state: RequirementsState) -> None:
        pass

    previous_state = make_state(confirmed_requirements=[make_confirmed_requirement("timeline", "we ship in Q3")])
    matrix = make_matrix(
        [make_entry("timeline", "Timeline", FillState.FILLED, citations=[make_citation("we ship in Q3")])]
    )

    result = asyncio.run(
        merge_requirements_state_forward(
            "engagement-1", previous_state, matrix, make_artifacts(), save, merged_at=FIXED
        )
    )

    assert result.contradictions == []
    assert len(result.confirmed_requirements) == 1


def test_reconfirming_a_section_with_a_different_quoted_citation_records_a_contradiction_and_keeps_the_latest():
    async def save(state: RequirementsState) -> None:
        pass

    previous_state = make_state(confirmed_requirements=[make_confirmed_requirement("timeline", "we ship in Q3")])
    matrix = make_matrix(
        [make_entry("timeline", "Timeline", FillState.FILLED, citations=[make_citation("we ship in Q1 now")])]
    )

    result = asyncio.run(
        merge_requirements_state_forward(
            "engagement-1", previous_state, matrix, make_artifacts(), save, merged_at=FIXED
        )
    )

    assert len(result.contradictions) == 1
    contradiction = result.contradictions[0]
    assert contradiction.section_key == "timeline"
    assert contradiction.previous_citation.quoted_text == "we ship in Q3"
    assert contradiction.new_citation.quoted_text == "we ship in Q1 now"
    assert len(result.confirmed_requirements) == 1
    assert result.confirmed_requirements[0].citations[0].quoted_text == "we ship in Q1 now"


def test_a_failed_matrix_contributes_no_new_confirmed_requirements_but_decisions_and_prior_state_still_carry_forward():
    async def save(state: RequirementsState) -> None:
        pass

    previous_state = make_state(
        confirmed_requirements=[make_confirmed_requirement("timeline", "we ship in Q3")],
        decisions=[make_decision("go with vendor A")],
    )
    matrix = make_matrix([], status=CoverageMatrixStatus.FAILED, error="classifier timed out")
    artifacts = make_artifacts(decisions=[make_decision("set budget at 50k")])

    result = asyncio.run(
        merge_requirements_state_forward("engagement-1", previous_state, matrix, artifacts, save, merged_at=FIXED)
    )

    assert [req.section_key for req in result.confirmed_requirements] == ["timeline"]
    assert [decision.text for decision in result.decisions] == ["go with vendor A", "set budget at 50k"]
    assert result.contradictions == []


def test_a_decisions_inference_marker_survives_the_merge_unchanged():
    async def save(state: RequirementsState) -> None:
        pass

    previous_state = make_state(decisions=[make_decision("go with vendor A", ClaimProvenance.STATED)])
    matrix = make_matrix([make_entry("timeline", "Timeline", FillState.EMPTY)])
    artifacts = make_artifacts(
        decisions=[make_decision("timeline likely slips a month", ClaimProvenance.INFERRED)]
    )

    result = asyncio.run(
        merge_requirements_state_forward("engagement-1", previous_state, matrix, artifacts, save, merged_at=FIXED)
    )

    provenance_by_text = {decision.text: decision.provenance for decision in result.decisions}
    assert provenance_by_text == {
        "go with vendor A": ClaimProvenance.STATED,
        "timeline likely slips a month": ClaimProvenance.INFERRED,
    }
