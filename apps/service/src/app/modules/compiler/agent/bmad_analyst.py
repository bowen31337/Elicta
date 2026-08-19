"""Runs the offline BMAD Analyst pass over an engagement's context pack (PRD FR-4.1, FR-4.2).

`run_bmad_analyst_pass` takes the pass itself as an injected callable rather
than importing the Claude Agent SDK directly, mirroring
`debrief/pipeline/bmad_analyst.py`'s `RunBmadAnalystChain`: no durable store
exists yet in this codebase, and this package stays decoupled from any
concrete vendor client. Whoever wires the app factory supplies the real
pass — built on the Claude Agent SDK per architecture §3.10/§3.11 — as
`RunBmadAnalystPass`.

This is the compile-time counterpart of `debrief/pipeline/bmad_analyst.py`'s
post-meeting chain: that one runs over a session's transcript to produce
debrief artifacts (PRD FR-8); this one runs offline, pre-meeting, over an
engagement's compiled context pack to produce the candidate question bank
itself (PRD FR-4.1, architecture §3.10). Assembling the final embedded
`candidate` table rows (PRD FR-4.3) and wiring `POST
/api/engagements/{id}/bank/compile` are both out of this feature's
footprint — this module's job ends at running the chain, enforcing its
PRD FR-4.1/FR-4.2 contract, and persisting the durable pass record.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .models import (
    AnalystBankCandidate,
    AnalystContextPack,
    BmadAnalystPassOutput,
    BmadAnalystPassStatus,
    BmadCandidateDraft,
    EngagementBmadAnalystPass,
)

MIN_CANDIDATES = 150
MAX_CANDIDATES = 300

RunBmadAnalystPass = Callable[[str, AnalystContextPack], Awaitable[BmadAnalystPassOutput]]
SaveEngagementBmadAnalystPass = Callable[[EngagementBmadAnalystPass], Awaitable[None]]


def build_bank_candidates(engagement_id: str, drafts: list[BmadCandidateDraft]) -> list[AnalystBankCandidate]:
    """Assign a durable id and `engagement_id` to each chain-returned candidate draft (PRD FR-4.1, FR-4.2).

    Ids are assigned `{engagement_id}-candidate-{index}` in the order the
    chain returned them, mirroring `compiler/bank/recompile.py`'s
    `inherited-open-question-{index}` convention -- the chain itself never
    names a real candidate id, since it has no visibility into what else the
    engagement's bank already holds.
    """

    return [
        AnalystBankCandidate(
            id=f"{engagement_id}-candidate-{index}",
            engagement_id=engagement_id,
            template_section=draft.template_section,
            trigger_types=draft.trigger_types,
            phrasing=draft.phrasing,
            stub=draft.stub,
            lang=draft.lang,
            priority=draft.priority,
            requires=draft.requires,
            authority_match=draft.authority_match,
            source_doc=draft.source_doc,
        )
        for index, draft in enumerate(drafts)
    ]


async def run_bmad_analyst_pass(
    engagement_id: str,
    context_pack: AnalystContextPack,
    engine: str,
    run_chain: RunBmadAnalystPass,
    save: SaveEngagementBmadAnalystPass,
    *,
    requested_at: datetime | None = None,
) -> EngagementBmadAnalystPass:
    """Run the BMAD Analyst pass over `context_pack` and persist the resulting candidate bank (PRD FR-4.1).

    PRD FR-4.1 requires the pass to emit 150-300 candidate questions; a
    chain run that returns a count outside that range is treated the same
    as a raised exception -- a vendor contract violation this stage can't
    safely present as a compiled bank, mirroring how
    `debrief/pipeline/bmad_analyst.py`'s chain treats a citation naming an
    unknown utterance. On success, every draft candidate is assigned a
    durable id via `build_bank_candidates` and the run persists as one
    `COMPLETE` `EngagementBmadAnalystPass`. On either failure mode, this
    persists a `FAILED` record with no candidates and re-raises nothing --
    same shape as `run_bmad_analyst_chain`'s failure handling, so an
    engagement that hasn't had the pass run yet stays distinguishable from
    one whose run failed.
    """

    requested_at = requested_at or datetime.now(UTC)

    try:
        output = await run_chain(engagement_id, context_pack)
        candidate_count = len(output.candidates)
        if not (MIN_CANDIDATES <= candidate_count <= MAX_CANDIDATES):
            raise ValueError(
                f"analyst pass produced {candidate_count} candidates, outside the "
                f"required {MIN_CANDIDATES}-{MAX_CANDIDATES} range (PRD FR-4.1)"
            )
        candidates = build_bank_candidates(engagement_id, output.candidates)
    except Exception as exc:
        failed = EngagementBmadAnalystPass(
            engagement_id=engagement_id,
            status=BmadAnalystPassStatus.FAILED,
            engine=engine,
            candidates=None,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = EngagementBmadAnalystPass(
        engagement_id=engagement_id,
        status=BmadAnalystPassStatus.COMPLETE,
        engine=engine,
        candidates=candidates,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
