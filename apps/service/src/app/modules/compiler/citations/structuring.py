"""Runs the schema-constrained structuring pass over already-extracted, citation-grounded claims (architecture §3.11, §14.4).

Architecture §14.4 is explicit about why this is a *second*, separate call:
document citations are incompatible with `output_config.format` in the same
request, so the compiler runs "an extraction pass with citations enabled,
then a structuring pass over the extracted claims with the schema applied."
`extraction.py` is the first call; this module is the second -- a request
with the candidate-record schema applied and no document content blocks (and
so no citations) at all.

This pass never asks the chain for `source_doc`: each `ClaimStructuringDraft`
names only the `claim_id` it structures, and `build_structured_candidates`
derives `source_doc` itself via `extraction.format_source_doc` against that
claim's already-validated citation -- the same "derive provenance ourselves,
never trust the model for it" reasoning `extraction.py`'s own
`_validate_citation` already applies to the first pass's citations.

`run_claim_structuring_pass` takes the pass itself as an injected callable
rather than importing the Claude Agent SDK directly, mirroring
`extraction.py`'s `run_document_extraction_pass` and `agent/bmad_analyst.py`'s
`run_bmad_analyst_pass`: this package stays decoupled from any concrete
vendor client. Whoever wires the app factory supplies the real pass -- a
Messages API call with `output_config.format` set to this pass's schema --
as `RunClaimStructuringPass`, and is responsible for feeding it the claims
`run_document_extraction_pass` already persisted. Persisting these candidates
into the `candidate` table (architecture §3.6) is out of this feature's
footprint -- this module's job ends at running the chain, deriving each
candidate's provenance, and persisting the durable pass record of
schema-valid candidates.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .extraction import format_source_doc
from .models import (
    ClaimStructuringDraft,
    ClaimStructuringOutput,
    ClaimStructuringPassStatus,
    EngagementClaimStructuringPass,
    ExtractedClaim,
    StructuredCitationCandidate,
)

RunClaimStructuringPass = Callable[[str, list[ExtractedClaim]], Awaitable[ClaimStructuringOutput]]
SaveEngagementClaimStructuringPass = Callable[[EngagementClaimStructuringPass], Awaitable[None]]


def build_structured_candidates(
    claims: list[ExtractedClaim], drafts: list[ClaimStructuringDraft]
) -> list[StructuredCitationCandidate]:
    """Assign a durable id and derive `source_doc` for each chain-returned structuring draft (architecture §3.6, §14.4).

    Raises `ValueError` if a draft names a `claim_id` the extraction pass
    never produced: this pass has no independent way to ground a candidate,
    so a fabricated `claim_id` would leave `source_doc` with no citation to
    derive from -- the same fail-the-run-rather-than-persist-ungrounded-data
    reasoning `extraction.py`'s `build_extracted_claims` uses for a citation
    naming an unknown document. Ids are assigned `{claim_id}-candidate`,
    tying each structured candidate back to the one claim it was built from.
    """

    claims_by_id = {claim.id: claim for claim in claims}

    candidates: list[StructuredCitationCandidate] = []
    for draft in drafts:
        claim = claims_by_id.get(draft.claim_id)
        if claim is None:
            raise ValueError(f"structuring draft names unknown claim_id {draft.claim_id!r}")

        candidates.append(
            StructuredCitationCandidate(
                id=f"{draft.claim_id}-candidate",
                template_section=draft.template_section,
                trigger_types=draft.trigger_types,
                phrasing=draft.phrasing,
                stub=draft.stub,
                lang=draft.lang,
                priority=draft.priority,
                requires=draft.requires,
                authority_match=draft.authority_match,
                source_doc=format_source_doc(claim.citation),
            )
        )

    return candidates


async def run_claim_structuring_pass(
    engagement_id: str,
    claims: list[ExtractedClaim],
    run_chain: RunClaimStructuringPass,
    save: SaveEngagementClaimStructuringPass,
    *,
    requested_at: datetime | None = None,
) -> EngagementClaimStructuringPass:
    """Run the schema-constrained structuring pass over `claims` and persist the resulting candidate records (architecture §14.4).

    On success, every draft candidate has a durable id and a `source_doc`
    derived from its originating claim's validated citation via
    `build_structured_candidates`, and the run persists as one `COMPLETE`
    `EngagementClaimStructuringPass`. If the chain raises, or any draft names
    a claim the extraction pass never produced, this persists a `FAILED`
    record with no candidates and re-raises nothing -- same shape as
    `run_document_extraction_pass`'s failure handling, so an engagement that
    hasn't had this pass run yet stays distinguishable from one whose run
    failed.
    """

    requested_at = requested_at or datetime.now(UTC)

    try:
        output = await run_chain(engagement_id, claims)
        candidates = build_structured_candidates(claims, output.candidates)
    except Exception as exc:
        failed = EngagementClaimStructuringPass(
            engagement_id=engagement_id,
            status=ClaimStructuringPassStatus.FAILED,
            candidates=None,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = EngagementClaimStructuringPass(
        engagement_id=engagement_id,
        status=ClaimStructuringPassStatus.COMPLETE,
        candidates=candidates,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
