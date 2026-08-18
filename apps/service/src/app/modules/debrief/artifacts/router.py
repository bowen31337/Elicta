"""HTTP surface for full PRD generation, gated on cross-meeting coverage (PRD FR-8.10).

`build_full_prd_router` takes both the coverage lookup and the actual
generation step as injected callables, mirroring every other router in this
codebase (`asr-record/router.py`, `engagement/api/router.py`): no persistence
layer and no full-PRD compiler live in this package. Whoever wires the app
factory (out of this feature's footprint) supplies real implementations and
mounts the returned router.

Coverage is computed from every `RequirementsCoverageMatrix` the engagement's
meetings have built (PRD FR-8.2, from `matrix.py`) via
`require_prd_generation_coverage`. A request that doesn't clear the FR-8.10
threshold never reaches `generate` at all — it fails fast with 409 and the
same explanatory message `PrdGenerationRefused` carries, so an operator sees
exactly which sections still need coverage instead of a bare rejection.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.modules.debrief.pipeline.models import BmadArtifactSet
from fastapi import APIRouter, HTTPException

from .models import RequirementsCoverageMatrix
from .prd_gate import DEFAULT_PRD_COVERAGE_THRESHOLD, PrdGenerationRefused, require_prd_generation_coverage

GetEngagementCoverageMatrices = Callable[[str], Awaitable[list[RequirementsCoverageMatrix]]]
GenerateFullPrd = Callable[[str], Awaitable[BmadArtifactSet]]


def build_full_prd_router(
    get_matrices: GetEngagementCoverageMatrices,
    generate: GenerateFullPrd,
    *,
    threshold: float = DEFAULT_PRD_COVERAGE_THRESHOLD,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["debrief-prd"])

    @router.post("/{engagement_id}/prd", response_model=BmadArtifactSet, status_code=201)
    async def generate_full_prd(engagement_id: str) -> BmadArtifactSet:
        matrices = await get_matrices(engagement_id)
        try:
            require_prd_generation_coverage(matrices, threshold=threshold)
        except PrdGenerationRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return await generate(engagement_id)

    return router
