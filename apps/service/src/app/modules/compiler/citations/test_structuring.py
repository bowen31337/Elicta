"""Tests for the schema-constrained claim-structuring pass and its provenance-derivation contract (architecture §14.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.modules.compiler.citations.extraction import format_source_doc
from app.modules.compiler.citations.models import (
    CitedSpan,
    ClaimStructuringDraft,
    ClaimStructuringOutput,
    ClaimStructuringPassStatus,
    EngagementClaimStructuringPass,
    ExtractedClaim,
)
from app.modules.compiler.citations.structuring import (
    build_structured_candidates,
    run_claim_structuring_pass,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_citation(**overrides) -> CitedSpan:
    defaults = {
        "document_id": "doc-1",
        "cited_text": "a new billing system",
        "start_char_index": 10,
        "end_char_index": 31,
    }
    defaults.update(overrides)
    return CitedSpan(**defaults)


def make_claim(**overrides) -> ExtractedClaim:
    defaults = {
        "id": "claim-0",
        "text": "The client wants a new billing system.",
        "citation": make_citation(),
    }
    defaults.update(overrides)
    return ExtractedClaim(**defaults)


def make_draft(**overrides) -> ClaimStructuringDraft:
    defaults = {
        "claim_id": "claim-0",
        "template_section": "current-state",
        "trigger_types": ["explicit-ask"],
        "phrasing": "What billing system does the client currently use?",
        "stub": "billing system",
        "lang": "en",
        "priority": 1,
    }
    defaults.update(overrides)
    return ClaimStructuringDraft(**defaults)


def make_output(drafts: list[ClaimStructuringDraft] | None = None) -> ClaimStructuringOutput:
    return ClaimStructuringOutput(candidates=drafts if drafts is not None else [make_draft()])


def make_run_chain(output: ClaimStructuringOutput | None = None, *, fail: bool = False):
    async def run_chain(engagement_id: str, claims: list[ExtractedClaim]) -> ClaimStructuringOutput:
        if fail:
            raise RuntimeError("structuring pass timed out")
        return output if output is not None else make_output()

    return run_chain


def test_build_structured_candidates_assigns_ids_and_derives_source_doc_from_the_claims_citation():
    claims = [make_claim()]
    drafts = [make_draft()]

    candidates = build_structured_candidates(claims, drafts)

    assert len(candidates) == 1
    assert candidates[0].id == "claim-0-candidate"
    assert candidates[0].source_doc == format_source_doc(claims[0].citation)


def test_build_structured_candidates_preserves_every_schema_field_from_the_draft():
    claims = [make_claim()]
    drafts = [
        make_draft(
            template_section="pain-points",
            trigger_types=["explicit-ask", "silence"],
            phrasing="What is the biggest pain point with {term}?",
            stub="pain point",
            lang="en",
            priority=2,
            requires=["claim-0-candidate-prereq"],
            authority_match=["product-owner"],
        )
    ]

    candidates = build_structured_candidates(claims, drafts)

    candidate = candidates[0]
    assert candidate.template_section == "pain-points"
    assert candidate.trigger_types == ["explicit-ask", "silence"]
    assert candidate.phrasing == "What is the biggest pain point with {term}?"
    assert candidate.stub == "pain point"
    assert candidate.lang == "en"
    assert candidate.priority == 2
    assert candidate.requires == ["claim-0-candidate-prereq"]
    assert candidate.authority_match == ["product-owner"]


def test_build_structured_candidates_raises_for_a_draft_naming_an_unknown_claim():
    claims = [make_claim()]
    drafts = [make_draft(claim_id="claim-unknown")]

    with pytest.raises(ValueError, match="unknown claim_id"):
        build_structured_candidates(claims, drafts)


def test_build_structured_candidates_derives_distinct_source_docs_for_distinct_claims():
    claims = [
        make_claim(id="claim-0", citation=make_citation(start_char_index=0, end_char_index=10)),
        make_claim(id="claim-1", citation=make_citation(start_char_index=20, end_char_index=30)),
    ]
    drafts = [make_draft(claim_id="claim-0"), make_draft(claim_id="claim-1")]

    candidates = build_structured_candidates(claims, drafts)

    assert candidates[0].source_doc != candidates[1].source_doc
    assert candidates[0].id == "claim-0-candidate"
    assert candidates[1].id == "claim-1-candidate"


def test_a_successful_run_persists_a_complete_record_with_a_source_doc_on_every_candidate():
    saved: list[EngagementClaimStructuringPass] = []

    async def save(record: EngagementClaimStructuringPass) -> None:
        saved.append(record)

    claims = [make_claim(id="claim-0"), make_claim(id="claim-1")]
    drafts = [make_draft(claim_id="claim-0"), make_draft(claim_id="claim-1")]

    result = asyncio.run(
        run_claim_structuring_pass(
            "engagement-1",
            claims,
            make_run_chain(make_output(drafts)),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == ClaimStructuringPassStatus.COMPLETE
    assert result.engagement_id == "engagement-1"
    assert result.candidates is not None
    assert len(result.candidates) == 2
    assert all(candidate.source_doc for candidate in result.candidates)
    assert saved == [result]


def test_a_failed_chain_persists_a_failed_record_with_no_candidates():
    saved: list[EngagementClaimStructuringPass] = []

    async def save(record: EngagementClaimStructuringPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_claim_structuring_pass(
            "engagement-1",
            [make_claim()],
            make_run_chain(fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == ClaimStructuringPassStatus.FAILED
    assert result.candidates is None
    assert result.error == "structuring pass timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_a_draft_naming_an_unknown_claim_fails_the_run_instead_of_persisting_an_ungrounded_candidate():
    saved: list[EngagementClaimStructuringPass] = []

    async def save(record: EngagementClaimStructuringPass) -> None:
        saved.append(record)

    bad_draft = make_draft(claim_id="claim-unknown")

    result = asyncio.run(
        run_claim_structuring_pass(
            "engagement-1",
            [make_claim()],
            make_run_chain(make_output([bad_draft])),
            save,
        )
    )

    assert result.status == ClaimStructuringPassStatus.FAILED
    assert result.candidates is None
    assert "unknown claim_id" in result.error
    assert saved == [result]


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    result = asyncio.run(
        run_claim_structuring_pass(
            "engagement-1",
            [make_claim()],
            make_run_chain(),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.completed_at >= result.requested_at
