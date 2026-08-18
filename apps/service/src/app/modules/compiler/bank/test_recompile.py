"""Tests for recompiling one meeting's bank, weighted toward inherited open questions (PRD FR-4.8)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.compiler.bank.models import BankCandidate
from app.modules.compiler.bank.recompile import (
    INHERITED_TEMPLATE_SECTION,
    InheritedOpenQuestion,
    recompile_meeting_bank,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candidate(candidate_id: str, priority: int, template_section: str = "scope") -> BankCandidate:
    return BankCandidate(id=candidate_id, template_section=template_section, phrasing=candidate_id, priority=priority)


def test_a_meeting_with_no_inherited_open_questions_recompiles_a_bank_identical_in_ranking_to_its_base_candidates():
    base = [make_candidate("c1", priority=1), make_candidate("c2", priority=2)]

    bank = recompile_meeting_bank("meeting-2", base, [], generated_at=FIXED)

    assert [c.id for c in bank.candidates] == ["c1", "c2"]
    assert [c.priority for c in bank.candidates] == [1, 2]
    assert all(not c.inherited_from_open_question for c in bank.candidates)
    assert bank.meeting_id == "meeting-2"
    assert bank.generated_at == FIXED


def test_inherited_open_questions_outrank_every_base_candidate():
    base = [make_candidate("c1", priority=1), make_candidate("c2", priority=2)]
    inherited = [
        InheritedOpenQuestion(text="what is the rollout timeline?", impact_rank=1),
        InheritedOpenQuestion(text="who owns budget sign-off?", impact_rank=2),
    ]

    bank = recompile_meeting_bank("meeting-2", base, inherited, generated_at=FIXED)

    assert [c.phrasing for c in bank.candidates] == [
        "what is the rollout timeline?",
        "who owns budget sign-off?",
        "c1",
        "c2",
    ]
    assert [c.priority for c in bank.candidates] == [1, 2, 3, 4]


def test_inherited_candidates_are_flagged_and_carry_the_carried_forward_template_section():
    inherited = [InheritedOpenQuestion(text="what is the rollout timeline?", impact_rank=1)]

    bank = recompile_meeting_bank("meeting-2", [], inherited, generated_at=FIXED)

    [candidate] = bank.candidates
    assert candidate.inherited_from_open_question is True
    assert candidate.template_section == INHERITED_TEMPLATE_SECTION
    assert candidate.priority == 1


def test_recompile_defaults_generated_at_to_now_when_not_supplied():
    bank = recompile_meeting_bank("meeting-2", [], [])

    assert bank.generated_at.tzinfo is not None
