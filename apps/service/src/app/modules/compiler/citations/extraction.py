"""Runs the offline document-extraction pass with native citations enabled (architecture §3.10, §3.11).

`run_document_extraction_pass` takes the pass itself as an injected callable
rather than importing the Claude Agent SDK directly, mirroring
`agent/bmad_analyst.py`'s `run_bmad_analyst_pass`: this package stays
decoupled from any concrete vendor client, and whoever wires the app factory
supplies the real pass -- a Messages API call with `citations: {enabled:
true}` on each document content block per architecture §3.11 -- as
`RunDocumentExtractionPass`. Feeding this pass's output into the structuring
pass (`agent/bmad_analyst.py`) as `AnalystContextPack` content, and wiring
this into `POST /api/engagements/{id}/bank/compile`, are both out of this
feature's footprint -- this module's job ends at running the extraction
chain, validating every claim's citation actually grounds in its named
source document, and persisting the durable pass record.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import (
    CitedSpan,
    DocumentExtractionOutput,
    EngagementDocumentExtractionPass,
    ExtractedClaim,
    ExtractedClaimDraft,
    ExtractionPassStatus,
    ExtractionSourceDocument,
)

RunDocumentExtractionPass = Callable[[str, list[ExtractionSourceDocument]], Awaitable[DocumentExtractionOutput]]
SaveEngagementDocumentExtractionPass = Callable[[EngagementDocumentExtractionPass], Awaitable[None]]


def _validate_citation(documents: dict[str, str], citation: CitedSpan) -> None:
    """Raise `ValueError` unless `citation` actually grounds in its named document's text.

    A citation naming a document the extraction pass was never given, a span
    past the end of that document's text, or a `cited_text` that doesn't
    match the substring at `[start_char_index, end_char_index)` would be
    indistinguishable from a fabricated citation -- the same failure mode
    `debrief/pipeline/bmad_analyst.py`'s chain treats as a run-failing
    vendor contract violation for a citation naming an unknown utterance_id.
    """

    if citation.document_id not in documents:
        raise ValueError(f"citation names unknown document_id {citation.document_id!r}")

    text = documents[citation.document_id]
    if citation.end_char_index <= citation.start_char_index:
        raise ValueError(
            f"citation end_char_index {citation.end_char_index} is not after "
            f"start_char_index {citation.start_char_index}"
        )
    if citation.end_char_index > len(text):
        raise ValueError(
            f"citation span [{citation.start_char_index}, {citation.end_char_index}) "
            f"is past the end of document {citation.document_id!r} ({len(text)} chars)"
        )

    actual = text[citation.start_char_index : citation.end_char_index]
    if actual != citation.cited_text:
        raise ValueError(
            f"citation cited_text does not match document {citation.document_id!r} "
            f"at [{citation.start_char_index}, {citation.end_char_index}): "
            f"expected {citation.cited_text!r}, found {actual!r}"
        )


def format_source_doc(citation: CitedSpan) -> str:
    """Format one validated citation as the `candidate.source_doc` TEXT value (architecture §3.6, §14.4).

    Architecture §14.4: native citations let the compiler populate
    `source_doc` "with a location rather than a filename" -- a bare
    `document_id` alone would regress to exactly the filename-only
    provenance that section calls out as insufficient, so this also encodes
    the `[start_char_index, end_char_index)` span that
    `_validate_citation` has already confirmed grounds in that document's
    text. Downstream candidate builders (`agent/bmad_analyst.py`,
    `techniques/hypothesis_verification.py`) are the ones that assign this
    string to a candidate's `source_doc`; wiring that assignment is out of
    this feature's footprint.
    """

    return f"{citation.document_id}#{citation.start_char_index}-{citation.end_char_index}"


def build_extracted_claims(
    documents: list[ExtractionSourceDocument], drafts: list[ExtractedClaimDraft]
) -> list[ExtractedClaim]:
    """Assign a durable id to each chain-returned claim draft and validate its citation (architecture §3.11).

    "The cited span persists for each extracted claim" is an invariant this
    function enforces, not just documents: a draft whose citation doesn't
    actually ground in the named document's text fails the whole run instead
    of silently persisting a claim with an ungrounded span, the same
    fail-the-run-rather-than-persist-partial-data reasoning
    `debrief/pipeline/citations.py`'s `build_citation_rows` uses for a claim
    with no citations at all. Ids are assigned `claim-{index}` in the order
    the chain returned them, mirroring `bmad_analyst.py`'s
    `build_bank_candidates` convention.
    """

    document_text_by_id = {document.document_id: document.text for document in documents}

    claims: list[ExtractedClaim] = []
    for index, draft in enumerate(drafts):
        _validate_citation(document_text_by_id, draft.citation)
        claims.append(ExtractedClaim(id=f"claim-{index}", text=draft.text, citation=draft.citation))

    return claims


async def run_document_extraction_pass(
    engagement_id: str,
    documents: list[ExtractionSourceDocument],
    run_chain: RunDocumentExtractionPass,
    save: SaveEngagementDocumentExtractionPass,
    *,
    requested_at: datetime | None = None,
) -> EngagementDocumentExtractionPass:
    """Run the citations-enabled extraction pass over `documents` and persist the grounded claims (architecture §3.11).

    On success, every draft claim's citation has been validated against its
    source document's text via `build_extracted_claims`, and the run
    persists as one `COMPLETE` `EngagementDocumentExtractionPass`. If the
    chain raises, or any claim's citation fails to ground, this persists a
    `FAILED` record with no claims and re-raises nothing -- same shape as
    `run_bmad_analyst_pass`'s failure handling, so an engagement that hasn't
    had this pass run yet stays distinguishable from one whose run failed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)

    try:
        output = await run_chain(engagement_id, documents)
        claims = build_extracted_claims(documents, output.claims)
    except Exception as exc:
        failed = EngagementDocumentExtractionPass(
            engagement_id=engagement_id,
            status=ExtractionPassStatus.FAILED,
            claims=None,
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = EngagementDocumentExtractionPass(
        engagement_id=engagement_id,
        status=ExtractionPassStatus.COMPLETE,
        claims=claims,
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await save(result)
    return result
