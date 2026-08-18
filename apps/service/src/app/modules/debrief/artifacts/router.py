"""HTTP surface for full PRD generation and standing requirements state (PRD FR-8.8, FR-8.9, FR-8.10).

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
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.modules.debrief.pipeline.models import BmadArtifactSet
from fastapi import APIRouter, HTTPException

from .models import RequirementsCoverageMatrix, RequirementsState
from .prd_gate import DEFAULT_PRD_COVERAGE_THRESHOLD, PrdGenerationRefused, require_prd_generation_coverage

GetEngagementCoverageMatrices = Callable[[str], Awaitable[list[RequirementsCoverageMatrix]]]
GenerateFullPrd = Callable[[str], Awaitable[BmadArtifactSet]]
GetRequirementsState = Callable[[str], Awaitable[RequirementsState | None]]


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
