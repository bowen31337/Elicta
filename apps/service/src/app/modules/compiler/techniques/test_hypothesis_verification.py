"""Tests for compiling verification questions from hypothesis-document claims (PRD FR-4.9)."""

from __future__ import annotations

from app.modules.compiler.techniques.hypothesis_verification import (
    VERIFICATION_TEMPLATE_SECTION,
    generate_verification_questions,
)
from app.modules.compiler.techniques.models import HypothesisDocumentClaim
from app.modules.engagement.documents.models import DocumentStatus


def make_claim(claim_id: str, text: str, status: DocumentStatus) -> HypothesisDocumentClaim:
    return HypothesisDocumentClaim(
        document_id="doc-1", claim_id=claim_id, text=text, document_status=status
    )


def test_one_verification_question_is_generated_per_hypothesis_claim():
    claims = [
        make_claim("c1", "the client's fiscal year starts in July", DocumentStatus.HYPOTHESIS),
        make_claim("c2", "procurement approval takes two weeks", DocumentStatus.HYPOTHESIS),
    ]

    candidates = generate_verification_questions(claims)

    assert len(candidates) == 2
    assert [c.id for c in candidates] == ["hypothesis-verification-c1", "hypothesis-verification-c2"]
    assert [c.priority for c in candidates] == [1, 2]
    assert all(c.template_section == VERIFICATION_TEMPLATE_SECTION for c in candidates)


def test_verification_question_phrasing_confirms_rather_than_asserts_the_claim():
    [candidate] = generate_verification_questions(
        [make_claim("c1", "the client's fiscal year starts in July", DocumentStatus.HYPOTHESIS)]
    )

    assert candidate.phrasing == 'Can you confirm: "the client\'s fiscal year starts in July"?'


def test_ground_truth_and_superseded_claims_do_not_generate_verification_questions():
    claims = [
        make_claim("c1", "settled fact", DocumentStatus.GROUND_TRUTH),
        make_claim("c2", "old and replaced", DocumentStatus.SUPERSEDED),
    ]

    assert generate_verification_questions(claims) == []


def test_only_hypothesis_claims_are_kept_when_statuses_are_mixed():
    claims = [
        make_claim("c1", "settled fact", DocumentStatus.GROUND_TRUTH),
        make_claim("c2", "a claim to verify", DocumentStatus.HYPOTHESIS),
        make_claim("c3", "old and replaced", DocumentStatus.SUPERSEDED),
    ]

    candidates = generate_verification_questions(claims)

    assert len(candidates) == 1
    assert candidates[0].id == "hypothesis-verification-c2"
    assert candidates[0].priority == 1


def test_no_claims_generates_an_empty_list():
    assert generate_verification_questions([]) == []
