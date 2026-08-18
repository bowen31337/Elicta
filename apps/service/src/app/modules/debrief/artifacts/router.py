"""HTTP surface for full PRD generation, standing requirements state, the per-meeting draft project brief, and the per-meeting decision log (PRD FR-8.4, FR-8.5, FR-8.8, FR-8.9, FR-8.10).

`build_full_prd_router` takes the coverage lookup, the generation step, and
(optionally) a requirements-state lookup as injected callables, mirroring
every other router in this codebase (`asr-record/router.py`,
`engagement/api/router.py`): no persistence layer and no full-PRD compiler
live in this package. Whoever wires the app factory (out of this feature's
footprint) supplies real implementations and mounts the returned router.

Coverage is computed from every `RequirementsCoverageMatrix` the engagement's
meetings have built (PRD FR-8.2, from `matrix.py`) via
`require_prd_generation_coverage`. A request that doesn't clear the FR-8.10
threshold never reaches `generate` at all — it fails fast with 409 and the
same explanatory message `PrdGenerationRefused` carries, so an operator sees
exactly which sections still need coverage instead of a bare rejection.

The full PRD is unreachable for most of an engagement's life because of that
gate, but its standing `RequirementsState` (PRD FR-8.9, from `state.py`)
updates after every meeting well before coverage clears. Its `decisions` each
carry a `provenance` of `STATED` or `INFERRED` (PRD FR-8.8) straight through
from the BMAD analyst chain — nothing in this router or in
`merge_requirements_state_forward` rewrites it — so a `GET` of that state
lets a UI render the inference marker on every decision as soon as it
exists, not only once a full PRD can be generated.

`build_project_brief_router` exposes that same early-availability property
for one artifact specifically: the draft project brief `run_bmad_analyst_chain`
(PRD FR-4.1, FR-8, in `debrief/pipeline`) already builds from a single
meeting's classified transcript and persists on its `SessionBmadAnalystChain`
(PRD FR-8.5). That draft needs no cross-meeting coverage at all — it is
grounded entirely in the one meeting's own content — so this is a plain
session-scoped `GET`, not gated the way full PRD generation is.

`build_decision_log_router` exposes the same `SessionBmadAnalystChain` for its
`decisions` instead: the decision and commitment log `run_bmad_analyst_chain`
already derives per meeting, recording what was agreed and `decided_by` whom
(PRD FR-8.4). Like the draft project brief, this needs no cross-meeting
coverage — it is a plain session-scoped `GET` of what that one meeting's chain
run already persisted, not a rebuild of the engagement-wide `decisions` list
`merge_requirements_state_forward` (PRD FR-8.9) accumulates in `state.py`.

`build_open_questions_router` exposes the same chain's `open_questions` the
same way, but ordered: the analyst chain assigns each question its
`impact_rank` (PRD FR-8.3) without guaranteeing it returned them in that
order, so this route sorts by `impact_rank` ascending before responding —
callers always see the list ranked by impact on the build, never in
whatever order the chain happened to produce them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from app.modules.debrief.pipeline.models import (
    BmadArtifactSet,
    DecisionLogEntry,
    OpenQuestion,
    ProjectBriefDraft,
    SessionBmadAnalystChain,
)

from .models import RequirementsCoverageMatrix, RequirementsState
from .prd_gate import (
    DEFAULT_PRD_COVERAGE_THRESHOLD,
    PrdGenerationRefused,
    require_prd_generation_coverage,
)

GetEngagementCoverageMatrices = Callable[[str], Awaitable[list[RequirementsCoverageMatrix]]]
GenerateFullPrd = Callable[[str], Awaitable[BmadArtifactSet]]
GetRequirementsState = Callable[[str], Awaitable[RequirementsState | None]]
GetSessionBmadAnalystChain = Callable[[str], Awaitable[SessionBmadAnalystChain | None]]


def build_full_prd_router(
    get_matrices: GetEngagementCoverageMatrices,
    generate: GenerateFullPrd,
    *,
    threshold: float = DEFAULT_PRD_COVERAGE_THRESHOLD,
    get_requirements_state: GetRequirementsState | None = None,
) -> APIRouter:
    """Build the full-PRD generation router, plus an optional requirements-state read.

    `get_requirements_state` mirrors `get_alignment` in
    `asr-record/router.py`: an optional injected dependency, so a caller that
    hasn't wired requirements-state persistence yet can still mount this
    router for full-PRD generation alone. When supplied, it backs a
    `GET /{engagement_id}/requirements-state` route exposing the engagement's
    standing `RequirementsState` (PRD FR-8.9) — including every decision's
    `provenance` marker (PRD FR-8.8) — well before the full PRD is reachable,
    since that is gated on cross-meeting coverage the engagement may not have
    cleared yet.
    """

    router = APIRouter(prefix="/api/engagements", tags=["debrief-prd"])

    @router.post("/{engagement_id}/prd", response_model=BmadArtifactSet, status_code=201)
    async def generate_full_prd(engagement_id: str) -> BmadArtifactSet:
        matrices = await get_matrices(engagement_id)
        try:
            require_prd_generation_coverage(matrices, threshold=threshold)
        except PrdGenerationRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return await generate(engagement_id)

    if get_requirements_state is not None:

        @router.get("/{engagement_id}/requirements-state", response_model=RequirementsState)
        async def get_engagement_requirements_state(engagement_id: str) -> RequirementsState:
            state = await get_requirements_state(engagement_id)
            if state is None:
                raise HTTPException(status_code=404, detail="requirements state not found")
            return state

    return router


def build_project_brief_router(get_chain: GetSessionBmadAnalystChain) -> APIRouter:
    """Build the per-meeting draft project brief read router (PRD FR-8.5).

    `get_chain` looks up the session's `SessionBmadAnalystChain` — the same
    durable record `run_bmad_analyst_chain` persists — rather than this
    package computing or caching the brief itself; this router is a plain
    read of what the pipeline already built. A session with no chain record
    yet, or one whose run `FAILED` (`artifacts` is `None`), has no draft
    project brief to return, so both cases 404 rather than one looking like
    a real brief and the other an error.
    """

    router = APIRouter(prefix="/api/sessions", tags=["debrief-project-brief"])

    @router.get("/{session_id}/project-brief", response_model=ProjectBriefDraft)
    async def get_session_project_brief(session_id: str) -> ProjectBriefDraft:
        chain = await get_chain(session_id)
        if chain is None or chain.artifacts is None:
            raise HTTPException(status_code=404, detail="draft project brief not found")
        return chain.artifacts.project_brief

    return router


def build_decision_log_router(get_chain: GetSessionBmadAnalystChain) -> APIRouter:
    """Build the per-meeting decision and commitment log read router (PRD FR-8.4).

    `get_chain` looks up the same session's `SessionBmadAnalystChain` the
    draft project brief route reads — this is a plain read of the
    `DecisionLogEntry` list `run_bmad_analyst_chain` already persisted, each
    entry recording what was agreed (`text`) and by whom (`decided_by`), not
    a recomputation. A session with no chain record yet, or one whose run
    `FAILED` (`artifacts` is `None`), has no decision log to return, so both
    cases 404 rather than one looking like an empty log and the other an
    error.
    """

    router = APIRouter(prefix="/api/sessions", tags=["debrief-decision-log"])

    @router.get("/{session_id}/decision-log", response_model=list[DecisionLogEntry])
    async def get_session_decision_log(session_id: str) -> list[DecisionLogEntry]:
        chain = await get_chain(session_id)
        if chain is None or chain.artifacts is None:
            raise HTTPException(status_code=404, detail="decision log not found")
        return chain.artifacts.decisions

    return router


def build_open_questions_router(get_chain: GetSessionBmadAnalystChain) -> APIRouter:
    """Build the per-meeting open-questions list read router, ranked by impact (PRD FR-8.3).

    `get_chain` looks up the same session's `SessionBmadAnalystChain` the
    draft project brief and decision log routes read. The chain's
    `open_questions` are re-sorted by `impact_rank` ascending before being
    returned — the analyst chain guarantees each question a rank, not that it
    already returned them in rank order — so the response is always the
    open-questions list ranked by impact on the build, not whatever order the
    chain produced. A session with no chain record yet, or one whose run
    `FAILED` (`artifacts` is `None`), has no open-questions list to return, so
    both cases 404 rather than one looking like an empty list and the other
    an error.
    """

    router = APIRouter(prefix="/api/sessions", tags=["debrief-open-questions"])

    @router.get("/{session_id}/open-questions", response_model=list[OpenQuestion])
    async def get_session_open_questions(session_id: str) -> list[OpenQuestion]:
        chain = await get_chain(session_id)
        if chain is None or chain.artifacts is None:
            raise HTTPException(status_code=404, detail="open questions list not found")
        return sorted(chain.artifacts.open_questions, key=lambda question: question.impact_rank)

    return router
