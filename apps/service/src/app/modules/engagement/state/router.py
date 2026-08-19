"""HTTP surface for an engagement's standing state: inherited open questions plus requirements state (PRD FR-3.11, FR-4.8, FR-8.9).

FR-3.11 is what this serves directly: a meeting inherits the standing
open-questions list and requirements state from the meetings before it,
rather than the operator re-entering that context.

`build_engagement_state_router` takes `get_inherited_open_questions` and
`get_requirements_state` as injected callables, mirroring every other router
in this codebase (`engagement/api/router.py`, `compiler/bank/router.py`): no
persistence layer for either lives in this package. Whoever wires the app
factory (out of this feature's footprint) supplies real implementations —
resolving an engagement to the open questions its most recent meeting raised
and to its standing `RequirementsState` — and mounts the returned router.

`RequirementsState` is imported directly from `debrief/artifacts/models.py`
rather than mirrored locally: unlike `EngagementContext` in
`engagement/meetings/models.py` (a curated subset of fields for a specific
inherit-at-creation flow), this route hands back the engagement's canonical
standing state verbatim, so reshaping it into a local copy would only invite
drift between the two representations of the same record.

The response is always a 200, even for an engagement with no prior meetings:
`inherited_open_questions` comes back empty and `requirements_state` comes
back `None` rather than a 404, since "no state yet" is a normal point in an
engagement's life (its first meeting), not an error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from app.modules.debrief.artifacts.models import RequirementsState

from .models import EngagementStateResponse, InheritedOpenQuestion

GetInheritedOpenQuestions = Callable[[str], Awaitable[list[InheritedOpenQuestion]]]
GetRequirementsState = Callable[[str], Awaitable[RequirementsState | None]]


def build_engagement_state_router(
    get_inherited_open_questions: GetInheritedOpenQuestions,
    get_requirements_state: GetRequirementsState,
) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagement-state"])

    @router.get(
        "/{engagement_id}/state",
        response_model=EngagementStateResponse,
        status_code=200,
    )
    async def get_engagement_state(engagement_id: str) -> EngagementStateResponse:
        inherited_open_questions = await get_inherited_open_questions(engagement_id)
        requirements_state = await get_requirements_state(engagement_id)
        return EngagementStateResponse(
            engagement_id=engagement_id,
            inherited_open_questions=sorted(
                inherited_open_questions, key=lambda question: question.impact_rank
            ),
            requirements_state=requirements_state,
        )

    return router
