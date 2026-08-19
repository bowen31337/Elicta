"""Tests for gating full PRD generation on requirements coverage across meetings (PRD FR-8.10)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.debrief.artifacts.models import (
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
)
from app.modules.debrief.artifacts.prd_gate import (
    PrdGenerationRefused,
    require_prd_generation_coverage,
    summarize_engagement_coverage,
)
from app.modules.debrief.pipeline.models import FillState

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_entry(section_key: str, title: str, fill_state: FillState) -> CoverageMatrixEntry:
    return CoverageMatrixEntry(section_key=section_key, title=title, fill_state=fill_state, utterance_ids=[], citations=[])


def make_matrix(
    entries: list[CoverageMatrixEntry], *, status: CoverageMatrixStatus = CoverageMatrixStatus.COMPLETE,
    session_id: str = "session-1", error: str | None = None,
) -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id=session_id,
        status=status,
        entries=entries,
        is_fully_covered=bool(entries) and all(entry.fill_state == FillState.FILLED for entry in entries),
        generated_at=FIXED,
        error=error,
    )


def test_a_section_is_covered_once_any_single_meeting_fills_it():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)],
            session_id="meeting-1",
        ),
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.EMPTY), make_entry("budget", "Budget", FillState.FILLED)],
            session_id="meeting-2",
        ),
    ]

    summary = summarize_engagement_coverage(matrices)

    assert summary.meeting_count == 2
    assert summary.total_sections == 2
    assert summary.covered_sections == 2
    assert summary.coverage_ratio == 1.0
    assert summary.missing_sections == []


def test_a_section_no_meeting_ever_filled_stays_missing():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)],
        ),
    ]

    summary = summarize_engagement_coverage(matrices)

    assert summary.total_sections == 2
    assert summary.covered_sections == 1
    assert summary.coverage_ratio == 0.5
    assert [section.section_key for section in summary.missing_sections] == ["budget"]


def test_a_failed_matrix_contributes_no_sections_and_no_coverage():
    matrices = [
        make_matrix([make_entry("timeline", "Timeline", FillState.FILLED)], session_id="meeting-1"),
        make_matrix([], status=CoverageMatrixStatus.FAILED, session_id="meeting-2", error="classifier timed out"),
    ]

    summary = summarize_engagement_coverage(matrices)

    assert summary.meeting_count == 2
    assert summary.total_sections == 1
    assert summary.covered_sections == 1
    assert summary.coverage_ratio == 1.0


def test_no_meetings_at_all_is_a_vacuous_zero_ratio_not_full_coverage():
    summary = summarize_engagement_coverage([])

    assert summary.meeting_count == 0
    assert summary.total_sections == 0
    assert summary.covered_sections == 0
    assert summary.coverage_ratio == 0.0
    assert summary.missing_sections == []


def test_require_returns_the_summary_once_the_default_full_coverage_threshold_is_cleared():
    matrices = [
        make_matrix([make_entry("timeline", "Timeline", FillState.FILLED)]),
    ]

    summary = require_prd_generation_coverage(matrices)

    assert summary.coverage_ratio == 1.0


def test_require_refuses_below_the_default_full_coverage_threshold():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)],
        ),
    ]

    with pytest.raises(PrdGenerationRefused) as excinfo:
        require_prd_generation_coverage(matrices)

    assert excinfo.value.summary.coverage_ratio == 0.5
    assert excinfo.value.threshold == 1.0
    assert "Budget" in str(excinfo.value)
    assert "50%" in str(excinfo.value)


def test_require_refuses_an_engagement_with_no_meetings_regardless_of_threshold():
    with pytest.raises(PrdGenerationRefused) as excinfo:
        require_prd_generation_coverage([], threshold=0.0)

    assert excinfo.value.summary.total_sections == 0


def test_require_honours_a_lower_custom_threshold():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)],
        ),
    ]

    summary = require_prd_generation_coverage(matrices, threshold=0.5)

    assert summary.coverage_ratio == 0.5
