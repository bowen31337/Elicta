"""Tests for the offline document-extraction pass and its citation-grounding contract (architecture §3.11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.modules.compiler.citations.extraction import (
    build_extracted_claims,
    format_source_doc,
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

FIXED = datetime(2026, 1, 1, tzinfo=UTC)

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


def test_a_quote_the_document_never_contained_still_fails_the_run():
    """The safety property, unchanged: an invented quote is not a citation.

    This is what citation grounding is for, and it is the one thing the
    relocation below must never soften.
    """

    mismatched = make_citation(cited_text="something the document never said")
    drafts = [make_draft(citation=mismatched)]

    with pytest.raises(ValueError, match="does not appear"):
        build_extracted_claims(make_documents(), drafts)


# ── Offsets are the model's arithmetic, and models are bad at arithmetic ──
#
# These three used to assert the opposite: that a citation whose numbers were
# wrong failed the whole pass. On a live run that cost every one of ~150
# drafted questions because a model quoted `…cross-dock.` and gave a span one
# character short of the full stop.
#
# The invariant worth keeping is that the quote genuinely appears in the named
# document. The offsets are derived data — so they are re-derived here rather
# than trusted, which makes the stored span provably right instead of merely
# self-consistent.


def test_a_span_that_runs_past_the_end_is_corrected_when_the_quote_is_real():
    out_of_bounds = make_citation(
        cited_text="Q3.", start_char_index=len(DOC_TEXT) - 3, end_char_index=len(DOC_TEXT) + 10
    )

    claims = build_extracted_claims(make_documents(), [make_draft(citation=out_of_bounds)])

    citation = claims[0].citation
    assert DOC_TEXT[citation.start_char_index : citation.end_char_index] == "Q3."


def test_a_backwards_span_is_corrected_when_the_quote_is_real():
    backwards = make_citation(start_char_index=10, end_char_index=10)

    claims = build_extracted_claims(make_documents(), [make_draft(citation=backwards)])

    citation = claims[0].citation
    assert citation.end_char_index > citation.start_char_index
    assert DOC_TEXT[citation.start_char_index : citation.end_char_index] == (
        "a new billing system"
    )


def test_the_live_off_by_one_that_cost_a_whole_pass():
    """A quote carrying one more character than its span, as seen in the wild."""

    quoted = "a new billing system"
    off_by_one = make_citation(
        cited_text=quoted,
        start_char_index=DOC_TEXT.index(quoted),
        end_char_index=DOC_TEXT.index(quoted) + len(quoted) - 1,
    )

    claims = build_extracted_claims(make_documents(), [make_draft(citation=off_by_one)])

    citation = claims[0].citation
    assert DOC_TEXT[citation.start_char_index : citation.end_char_index] == quoted


def test_the_stored_quote_is_the_document_s_own_words_not_the_model_s():
    """A strengthening, not a loosening.

    Before, `cited_text` was whatever the model typed, checked equal to the
    span. Now it is taken from the document itself, so an artifact quotes its
    source verbatim even when the model retyped it slightly.
    """

    text = "The client wants\na new billing system by Q3."
    documents = [ExtractionSourceDocument(document_id="doc-1", text=text)]
    # The model collapses the newline to a space, as they do.
    citation = make_citation(cited_text="The client wants a new billing system")

    claims = build_extracted_claims(documents, [make_draft(citation=citation)])

    stored = claims[0].citation
    assert stored.cited_text == text[stored.start_char_index : stored.end_char_index]
    assert "\n" in stored.cited_text


def test_a_quote_appearing_twice_resolves_to_the_one_the_model_meant():
    text = "billing system. Then later, the billing system again."
    documents = [ExtractionSourceDocument(document_id="doc-1", text=text)]
    second = text.index("billing system", 10)
    citation = make_citation(
        cited_text="billing system", start_char_index=second + 1, end_char_index=second + 5
    )

    claims = build_extracted_claims(documents, [make_draft(citation=citation)])

    assert claims[0].citation.start_char_index == second


def test_format_source_doc_encodes_the_corrected_span():
    """The span is what a reader is sent to, so it has to be the real one."""

    quoted = "a new billing system"
    off_by_one = make_citation(
        cited_text=quoted,
        start_char_index=0,
        end_char_index=3,
    )

    claims = build_extracted_claims(make_documents(), [make_draft(citation=off_by_one)])

    start = DOC_TEXT.index(quoted)
    assert format_source_doc(claims[0].citation) == f"doc-1#{start}-{start + len(quoted)}"


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
    # The wording moved from "does not match" to "does not appear" when spans
    # stopped being trusted: the failure is that the document never contained
    # the quote, which is the fabrication this check exists to catch.
    assert "does not appear" in result.error
    assert saved == [result]


def test_format_source_doc_encodes_the_document_id_and_char_span():
    citation = make_citation()

    source_doc = format_source_doc(citation)

    start = DOC_TEXT.index("a new billing system")
    end = start + len("a new billing system")
    assert source_doc == f"doc-1#{start}-{end}"


def test_format_source_doc_differs_for_citations_naming_different_spans():
    first = format_source_doc(make_citation())
    second = format_source_doc(
        make_citation(cited_text="Q3.", start_char_index=len(DOC_TEXT) - 3, end_char_index=len(DOC_TEXT))
    )

    assert first != second


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
