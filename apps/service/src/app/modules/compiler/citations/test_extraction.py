"""Tests for the offline document-extraction pass and its citation-grounding contract (architecture §3.11)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.modules.compiler.citations.extraction import (
    build_extracted_claims,
    run_document_extraction_pass,
)
from app.modules.compiler.citations.models import (
    CitedSpan,
    DocumentExtractionOutput,
    EngagementDocumentExtractionPass,
    ExtractedClaimDraft,
    ExtractionPassStatus,
    ExtractionSourceDocument,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)

DOC_TEXT = "The client wants a new billing system by Q3."


def make_documents() -> list[ExtractionSourceDocument]:
    return [ExtractionSourceDocument(document_id="doc-1", text=DOC_TEXT)]


def make_citation(**overrides) -> CitedSpan:
    defaults = {
        "document_id": "doc-1",
        "cited_text": "a new billing system",
        "start_char_index": DOC_TEXT.index("a new billing system"),
        "end_char_index": DOC_TEXT.index("a new billing system") + len("a new billing system"),
    }
    defaults.update(overrides)
    return CitedSpan(**defaults)


def make_draft(**overrides) -> ExtractedClaimDraft:
    defaults = {"text": "The client wants a new billing system.", "citation": make_citation()}
    defaults.update(overrides)
    return ExtractedClaimDraft(**defaults)


def make_output(drafts: list[ExtractedClaimDraft] | None = None) -> DocumentExtractionOutput:
    return DocumentExtractionOutput(claims=drafts if drafts is not None else [make_draft()])


def make_run_chain(output: DocumentExtractionOutput | None = None, *, fail: bool = False):
    async def run_chain(
        engagement_id: str, documents: list[ExtractionSourceDocument]
    ) -> DocumentExtractionOutput:
        if fail:
            raise RuntimeError("extraction pass timed out")
        return output if output is not None else make_output()

    return run_chain


def test_build_extracted_claims_assigns_ids_in_order_and_preserves_citations():
    drafts = [make_draft(text="first claim"), make_draft(text="second claim")]

    claims = build_extracted_claims(make_documents(), drafts)

    assert [claim.id for claim in claims] == ["claim-0", "claim-1"]
    assert claims[0].text == "first claim"
    assert claims[0].citation.cited_text == "a new billing system"


def test_build_extracted_claims_raises_for_a_citation_naming_an_unknown_document():
    drafts = [make_draft(citation=make_citation(document_id="doc-unknown"))]

    with pytest.raises(ValueError, match="unknown document_id"):
        build_extracted_claims(make_documents(), drafts)


def test_build_extracted_claims_raises_when_cited_text_does_not_match_the_source_span():
    mismatched = make_citation(cited_text="something the document never said")
    drafts = [make_draft(citation=mismatched)]

    with pytest.raises(ValueError, match="does not match"):
        build_extracted_claims(make_documents(), drafts)


def test_build_extracted_claims_raises_when_the_span_runs_past_the_end_of_the_document():
    out_of_bounds = make_citation(
        cited_text="Q3.", start_char_index=len(DOC_TEXT) - 3, end_char_index=len(DOC_TEXT) + 10
    )
    drafts = [make_draft(citation=out_of_bounds)]

    with pytest.raises(ValueError, match="past the end"):
        build_extracted_claims(make_documents(), drafts)


def test_build_extracted_claims_raises_when_end_is_not_after_start():
    backwards = make_citation(start_char_index=10, end_char_index=10)
    drafts = [make_draft(citation=backwards)]

    with pytest.raises(ValueError, match="is not after"):
        build_extracted_claims(make_documents(), drafts)


def test_a_successful_run_persists_a_complete_record_with_the_cited_span_on_every_claim():
    saved: list[EngagementDocumentExtractionPass] = []

    async def save(record: EngagementDocumentExtractionPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_document_extraction_pass(
            "engagement-1",
            make_documents(),
            make_run_chain(make_output([make_draft(), make_draft(text="another claim")])),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == ExtractionPassStatus.COMPLETE
    assert result.engagement_id == "engagement-1"
    assert result.claims is not None
    assert len(result.claims) == 2
    assert all(claim.citation.cited_text == "a new billing system" for claim in result.claims)
    assert all(claim.citation.document_id == "doc-1" for claim in result.claims)
    assert saved == [result]


def test_a_failed_chain_persists_a_failed_record_with_no_claims():
    saved: list[EngagementDocumentExtractionPass] = []

    async def save(record: EngagementDocumentExtractionPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_document_extraction_pass(
            "engagement-1",
            make_documents(),
            make_run_chain(fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == ExtractionPassStatus.FAILED
    assert result.claims is None
    assert result.error == "extraction pass timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_an_ungrounded_citation_fails_the_run_instead_of_persisting_a_bad_span():
    saved: list[EngagementDocumentExtractionPass] = []

    async def save(record: EngagementDocumentExtractionPass) -> None:
        saved.append(record)

    bad_draft = make_draft(citation=make_citation(cited_text="fabricated quote"))

    result = asyncio.run(
        run_document_extraction_pass(
            "engagement-1",
            make_documents(),
            make_run_chain(make_output([bad_draft])),
            save,
        )
    )

    assert result.status == ExtractionPassStatus.FAILED
    assert result.claims is None
    assert "does not match" in result.error
    assert saved == [result]


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    result = asyncio.run(
        run_document_extraction_pass(
            "engagement-1",
            make_documents(),
            make_run_chain(),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.completed_at >= result.requested_at
