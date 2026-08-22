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

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

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


_WHITESPACE = re.compile(r"\s+")


def _whitespace_flexible(quote: str) -> re.Pattern[str]:
    """`quote` as a pattern where any run of whitespace matches any other.

    Documents arrive with paragraph breaks in them — `extract_text` joins Word
    paragraphs with a newline — and a model quoting across one writes a space.
    Treating those as the same character is not a loosening of grounding: every
    other character still has to match exactly, and the span that comes back
    is a real span of the real document.
    """

    return re.compile(
        r"\s+".join(re.escape(part) for part in _WHITESPACE.split(quote.strip()) if part)
    )


def _locate(text: str, citation: CitedSpan) -> tuple[int, int] | None:
    """Where `cited_text` actually is, or `None` if it is not there at all.

    Nearest to where the model said, so a phrase occurring twice resolves to
    the one it meant rather than the first in the file.
    """

    quote = citation.cited_text
    claimed = citation.start_char_index

    occurrences = sorted(
        {(found, found + len(quote)) for found in _all_occurrences(text, quote)}
    )
    if not occurrences:
        occurrences = sorted(
            (match.start(), match.end())
            for match in _whitespace_flexible(quote).finditer(text)
        )
    if not occurrences:
        return None
    return min(occurrences, key=lambda span: abs(span[0] - claimed))


def _all_occurrences(text: str, quote: str) -> list[int]:
    found: list[int] = []
    at = text.find(quote)
    while at != -1:
        found.append(at)
        at = text.find(quote, at + 1)
    return found


def _ground_citation(documents: dict[str, str], citation: CitedSpan) -> CitedSpan:
    """The citation with its span re-derived from where the quote really is.

    A citation naming a document the pass was never given, or quoting text that
    document does not contain, is indistinguishable from a fabricated one and
    still fails the run -- the same vendor-contract violation
    `debrief/pipeline/bmad_analyst.py` treats as fatal.

    What no longer fails the run is arithmetic. A model that quotes the
    document correctly and miscounts the offsets by a character has produced a
    grounded claim with a wrong number attached, and failing ~150 drafted
    questions over it (which happened) serves nobody. The offsets are derived
    data, so they are derived here: the returned span is the real location, and
    `cited_text` becomes the document's own text for it, which is stricter than
    trusting the model's rendition of its own quote.
    """

    if citation.document_id not in documents:
        raise ValueError(f"citation names unknown document_id {citation.document_id!r}")

    text = documents[citation.document_id]
    located = _locate(text, citation)
    if located is None:
        raise ValueError(
            f"citation cited_text does not appear in document "
            f"{citation.document_id!r}: {citation.cited_text!r}"
        )

    start, end = located
    return citation.model_copy(
        update={
            "start_char_index": start,
            "end_char_index": end,
            "cited_text": text[start:end],
        }
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
        grounded = _ground_citation(document_text_by_id, draft.citation)
        claims.append(ExtractedClaim(id=f"claim-{index}", text=draft.text, citation=grounded))

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

    requested_at = requested_at or datetime.now(UTC)

    try:
        output = await run_chain(engagement_id, documents)
        claims = build_extracted_claims(documents, output.claims)
    except Exception as exc:
        failed = EngagementDocumentExtractionPass(
            engagement_id=engagement_id,
            status=ExtractionPassStatus.FAILED,
            claims=None,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = EngagementDocumentExtractionPass(
        engagement_id=engagement_id,
        status=ExtractionPassStatus.COMPLETE,
        claims=claims,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
