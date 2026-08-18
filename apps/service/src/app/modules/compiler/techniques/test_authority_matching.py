"""Tests for scoring and persisting each candidate's authority_match value against a meeting's attendees (PRD FR-4.7)."""

from __future__ import annotations

import asyncio

from app.modules.compiler.techniques.authority_matching import (
    CandidateAuthorityMatch,
    compute_bank_authority_matches,
    compute_candidate_authority_match,
    persist_candidate_authority_matches,
)
from app.modules.compiler.techniques.models import CandidateAuthorityRequirement
from app.modules.engagement.meetings.models import Attendee


def make_attendee(attendee_id: str, **overrides) -> Attendee:
    defaults = {"meeting_id": "meeting-1"}
    defaults.update(overrides)
    return Attendee(id=attendee_id, **defaults)


def test_no_required_authority_scores_one_regardless_of_attendees():
    assert compute_candidate_authority_match([], []) == 1.0
    assert compute_candidate_authority_match([], [make_attendee("a1", role="Engineer")]) == 1.0


def test_required_authority_with_no_attendees_scores_zero():
    assert compute_candidate_authority_match(["Head of Procurement"], []) == 0.0


def test_required_authority_matched_by_role_scores_one():
    attendees = [make_attendee("a1", role="Head of Procurement")]

    assert compute_candidate_authority_match(["Head of Procurement"], attendees) == 1.0


def test_role_matching_is_case_insensitive():
    attendees = [make_attendee("a1", role="head of procurement")]

    assert compute_candidate_authority_match(["Head of Procurement"], attendees) == 1.0


def test_required_authority_matched_by_business_function_scores_one():
    attendees = [make_attendee("a1", business_function="Procurement")]

    assert compute_candidate_authority_match(["Procurement"], attendees) == 1.0


def test_required_authority_matched_by_decision_authority_scores_one():
    attendees = [make_attendee("a1", decision_authority="Budget sign-off")]

    assert compute_candidate_authority_match(["Budget sign-off"], attendees) == 1.0


def test_required_authority_matched_by_domain_expertise_scores_one():
    attendees = [make_attendee("a1", domain_expertise=["Payments", "Fraud"])]

    assert compute_candidate_authority_match(["Fraud"], attendees) == 1.0


def test_unmatched_required_authority_scores_zero():
    attendees = [make_attendee("a1", role="Engineer")]

    assert compute_candidate_authority_match(["Head of Procurement"], attendees) == 0.0


def test_partially_covered_requirement_scores_proportionally():
    attendees = [make_attendee("a1", role="Head of Procurement")]

    score = compute_candidate_authority_match(["Head of Procurement", "Head of Legal"], attendees)

    assert score == 0.5


def test_requirement_covered_across_multiple_attendees_scores_one():
    attendees = [
        make_attendee("a1", role="Head of Procurement"),
        make_attendee("a2", role="Head of Legal"),
    ]

    score = compute_candidate_authority_match(["Head of Procurement", "Head of Legal"], attendees)

    assert score == 1.0


def test_compute_bank_authority_matches_scores_every_candidate_against_the_same_roster():
    attendees = [make_attendee("a1", role="Head of Procurement")]
    requirements = [
        CandidateAuthorityRequirement(candidate_id="c1", required_authority=["Head of Procurement"]),
        CandidateAuthorityRequirement(candidate_id="c2", required_authority=["Head of Legal"]),
        CandidateAuthorityRequirement(candidate_id="c3", required_authority=[]),
    ]

    matches = compute_bank_authority_matches(requirements, attendees)

    assert matches == [
        CandidateAuthorityMatch(candidate_id="c1", authority_match=1.0),
        CandidateAuthorityMatch(candidate_id="c2", authority_match=0.0),
        CandidateAuthorityMatch(candidate_id="c3", authority_match=1.0),
    ]


def test_persist_candidate_authority_matches_saves_every_computed_value():
    saved: list[CandidateAuthorityMatch] = []

    async def save(match: CandidateAuthorityMatch) -> None:
        saved.append(match)

    attendees = [make_attendee("a1", role="Head of Procurement")]
    requirements = [
        CandidateAuthorityRequirement(candidate_id="c1", required_authority=["Head of Procurement"]),
        CandidateAuthorityRequirement(candidate_id="c2", required_authority=["Head of Legal"]),
    ]

    result = asyncio.run(persist_candidate_authority_matches(requirements, attendees, save))

    assert saved == result
    assert [m.candidate_id for m in saved] == ["c1", "c2"]
    assert [m.authority_match for m in saved] == [1.0, 0.0]
