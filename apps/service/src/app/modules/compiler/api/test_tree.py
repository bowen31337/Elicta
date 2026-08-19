"""Tests for grouping an engagement's compiled candidate set into a reviewable tree (PRD FR-4.8)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.compiler.api.models import BankCandidate
from app.modules.compiler.api.tree import build_question_bank_tree

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_candidate(candidate_id: str, template_section: str, priority: int) -> BankCandidate:
    return BankCandidate(id=candidate_id, template_section=template_section, phrasing=candidate_id, priority=priority)


def test_groups_candidates_by_template_section_preserving_within_section_order():
    candidates = [
        make_candidate("c-scope-1", "scope", 1),
        make_candidate("c-scope-2", "scope", 2),
        make_candidate("c-timeline-1", "timeline", 3),
        make_candidate("c-budget-1", "budget", 4),
    ]

    tree = build_question_bank_tree("engagement-1", candidates, generated_at=FIXED)

    assert tree.engagement_id == "engagement-1"
    assert tree.generated_at == FIXED
    assert [section.template_section for section in tree.sections] == ["scope", "timeline", "budget"]
    assert [c.id for c in tree.sections[0].candidates] == ["c-scope-1", "c-scope-2"]
    assert [c.id for c in tree.sections[1].candidates] == ["c-timeline-1"]
    assert [c.id for c in tree.sections[2].candidates] == ["c-budget-1"]


def test_sections_are_ordered_by_first_candidate_appearance_even_when_interleaved():
    candidates = [
        make_candidate("c-scope-1", "scope", 1),
        make_candidate("c-timeline-1", "timeline", 2),
        make_candidate("c-scope-2", "scope", 3),
    ]

    tree = build_question_bank_tree("engagement-1", candidates)

    assert [section.template_section for section in tree.sections] == ["scope", "timeline"]
    assert [c.id for c in tree.sections[0].candidates] == ["c-scope-1", "c-scope-2"]


def test_empty_candidates_produces_an_empty_tree():
    tree = build_question_bank_tree("engagement-1", [])

    assert tree.sections == []


def test_build_question_bank_tree_defaults_generated_at_to_now():
    tree = build_question_bank_tree("engagement-1", [])

    assert tree.generated_at.tzinfo is not None
