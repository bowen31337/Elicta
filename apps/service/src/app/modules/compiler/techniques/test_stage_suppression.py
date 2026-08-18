"""Tests for suppressing solution- and epic-shaped candidates at discovery stage (PRD FR-4.6)."""

from __future__ import annotations

from app.modules.compiler.bank.models import BankCandidate
from app.modules.compiler.techniques.models import (
    CandidateShape,
    EngagementStage,
    ShapedCandidate,
)
from app.modules.compiler.techniques.stage_suppression import (
    suppress_out_of_stage_candidates,
)


def make_shaped(candidate_id: str, priority: int, shape: CandidateShape) -> ShapedCandidate:
    return ShapedCandidate(
        candidate=BankCandidate(
            id=candidate_id, template_section="scope", phrasing=candidate_id, priority=priority
        ),
        shape=shape,
    )


def test_solution_and_epic_shaped_candidates_are_suppressed_at_discovery_stage():
    shaped_candidates = [
        make_shaped("c1", 1, CandidateShape.PROBLEM),
        make_shaped("c2", 2, CandidateShape.SOLUTION),
        make_shaped("c3", 3, CandidateShape.EPIC),
    ]

    result = suppress_out_of_stage_candidates(shaped_candidates, EngagementStage.DISCOVERY)

    assert [c.id for c in result.candidates] == ["c1"]
    assert result.suppressed_solution_count == 1
    assert result.suppressed_epic_count == 1


def test_problem_shaped_candidates_keep_their_priority_and_relative_order():
    shaped_candidates = [
        make_shaped("c1", 1, CandidateShape.PROBLEM),
        make_shaped("c2", 2, CandidateShape.SOLUTION),
        make_shaped("c3", 3, CandidateShape.PROBLEM),
    ]

    result = suppress_out_of_stage_candidates(shaped_candidates, EngagementStage.DISCOVERY)

    assert [c.id for c in result.candidates] == ["c1", "c3"]
    assert [c.priority for c in result.candidates] == [1, 3]


def test_no_suppression_outside_discovery_stage():
    shaped_candidates = [
        make_shaped("c1", 1, CandidateShape.PROBLEM),
        make_shaped("c2", 2, CandidateShape.SOLUTION),
        make_shaped("c3", 3, CandidateShape.EPIC),
    ]

    result = suppress_out_of_stage_candidates(shaped_candidates, EngagementStage.REQUIREMENTS)

    assert [c.id for c in result.candidates] == ["c1", "c2", "c3"]
    assert result.suppressed_solution_count == 0
    assert result.suppressed_epic_count == 0


def test_no_candidates_generates_a_zero_suppression_count():
    result = suppress_out_of_stage_candidates([], EngagementStage.DISCOVERY)

    assert result.candidates == []
    assert result.suppressed_solution_count == 0
    assert result.suppressed_epic_count == 0


def test_all_problem_shaped_candidates_suppresses_nothing():
    shaped_candidates = [
        make_shaped("c1", 1, CandidateShape.PROBLEM),
        make_shaped("c2", 2, CandidateShape.PROBLEM),
    ]

    result = suppress_out_of_stage_candidates(shaped_candidates, EngagementStage.DISCOVERY)

    assert len(result.candidates) == 2
    assert result.suppressed_solution_count == 0
    assert result.suppressed_epic_count == 0
