"""Tests for building the requirements coverage matrix artifact (PRD FR-8.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.artifacts.matrix import build_coverage_matrix
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
)
from app.modules.debrief.pipeline.models import (
    ClassifiedUtterance,
    CoverageSlotState,
    FillState,
    SectionClassificationStatus,
    SessionSectionClassification,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_utterance(utterance_id: str, section_key: str, start: float, end: float) -> ClassifiedUtterance:
    return ClassifiedUtterance(
        utterance_id=utterance_id,
        session_id="session-1",
        start_seconds=start,
        end_seconds=end,
        speaker_tag="alice",
        verbatim_text="verbatim",
        cleaned_text="cleaned",
        section_key=section_key,
    )


def make_classification(
    *, slots: list[CoverageSlotState], utterances: list[ClassifiedUtterance], status: SectionClassificationStatus,
    error: str | None = None,
) -> SessionSectionClassification:
    return SessionSectionClassification(
        session_id="session-1",
        status=status,
        engine="classifier-a",
        utterances=utterances,
        slots=slots,
        requested_at=FIXED,
        completed_at=FIXED,
        error=error,
    )


def make_cite(citation: CoverageCitation | None = None, *, fail: bool = False):
    async def cite(session_id: str, start_seconds: float, end_seconds: float) -> CoverageCitation:
        if fail:
            raise ValueError("record path does not cover this span")
        return citation or CoverageCitation(
            session_id=session_id,
            engine="record-path-engine",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            quoted_text="quoted",
            transcript_completed_at=FIXED,
        )

    return cite


def test_a_filled_slot_is_grounded_with_a_citation_spanning_its_utterances():
    saved: list[RequirementsCoverageMatrix] = []

    async def save(matrix: RequirementsCoverageMatrix) -> None:
        saved.append(matrix)

    classification = make_classification(
        slots=[
            CoverageSlotState(
                section_key="timeline", title="Timeline", fill_state=FillState.FILLED,
                utterance_ids=["utt-1", "utt-2"],
            ),
            CoverageSlotState(section_key="budget", title="Budget", fill_state=FillState.EMPTY, utterance_ids=[]),
        ],
        utterances=[
            make_utterance("utt-1", "timeline", 0.0, 1.0),
            make_utterance("utt-2", "timeline", 1.0, 2.5),
        ],
        status=SectionClassificationStatus.COMPLETE,
    )

    result = asyncio.run(build_coverage_matrix(classification, make_cite(), save, generated_at=FIXED))

    assert result.status == CoverageMatrixStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.generated_at == FIXED
    assert result.is_fully_covered is False

    entries_by_key = {entry.section_key: entry for entry in result.entries}
    timeline = entries_by_key["timeline"]
    assert timeline.fill_state == FillState.FILLED
    assert timeline.utterance_ids == ["utt-1", "utt-2"]
    assert len(timeline.citations) == 1
    assert timeline.citations[0].start_seconds == 0.0
    assert timeline.citations[0].end_seconds == 2.5

    budget = entries_by_key["budget"]
    assert budget.fill_state == FillState.EMPTY
    assert budget.citations == []
    assert saved == [result]


def test_a_matrix_with_every_slot_filled_is_fully_covered():
    async def save(matrix: RequirementsCoverageMatrix) -> None:
        pass

    classification = make_classification(
        slots=[
            CoverageSlotState(
                section_key="timeline", title="Timeline", fill_state=FillState.FILLED, utterance_ids=["utt-1"]
            ),
        ],
        utterances=[make_utterance("utt-1", "timeline", 0.0, 1.0)],
        status=SectionClassificationStatus.COMPLETE,
    )

    result = asyncio.run(build_coverage_matrix(classification, make_cite(), save))

    assert result.is_fully_covered is True


def test_a_non_complete_classification_run_persists_a_failed_matrix_with_no_entries():
    saved: list[RequirementsCoverageMatrix] = []

    async def save(matrix: RequirementsCoverageMatrix) -> None:
        saved.append(matrix)

    classification = make_classification(
        slots=[], utterances=[], status=SectionClassificationStatus.FAILED, error="classification vendor timed out",
    )

    result = asyncio.run(build_coverage_matrix(classification, make_cite(), save, generated_at=FIXED))

    assert result.status == CoverageMatrixStatus.FAILED
    assert result.entries == []
    assert result.is_fully_covered is False
    assert result.error == "classification vendor timed out"
    assert result.generated_at == FIXED
    assert saved == [result]


def test_a_citation_failure_on_a_filled_slot_persists_a_failed_matrix_instead_of_a_partial_one():
    saved: list[RequirementsCoverageMatrix] = []

    async def save(matrix: RequirementsCoverageMatrix) -> None:
        saved.append(matrix)

    classification = make_classification(
        slots=[
            CoverageSlotState(
                section_key="timeline", title="Timeline", fill_state=FillState.FILLED, utterance_ids=["utt-1"]
            ),
        ],
        utterances=[make_utterance("utt-1", "timeline", 0.0, 1.0)],
        status=SectionClassificationStatus.COMPLETE,
    )

    result = asyncio.run(build_coverage_matrix(classification, make_cite(fail=True), save))

    assert result.status == CoverageMatrixStatus.FAILED
    assert result.entries == []
    assert result.error == "record path does not cover this span"
    assert saved == [result]


def test_no_slots_persists_a_vacuously_fully_covered_complete_matrix():
    async def save(matrix: RequirementsCoverageMatrix) -> None:
        pass

    classification = make_classification(slots=[], utterances=[], status=SectionClassificationStatus.COMPLETE)

    result = asyncio.run(build_coverage_matrix(classification, make_cite(), save))

    assert result.status == CoverageMatrixStatus.COMPLETE
    assert result.entries == []
    assert result.is_fully_covered is True
