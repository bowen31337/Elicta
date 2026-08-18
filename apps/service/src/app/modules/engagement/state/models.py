"""Domain types for an engagement's reference claims and standing state (PRD FR-3.12, FR-4.8, FR-8.9).

A reference claim is one assertion surfaced from an engagement's context
pack — background material gathered about the client ahead of a session
(PRD FR-3.1 covers the engagement-level background this pack builds on).
`verify_with_client` marks a claim the user isn't confident enough in to
treat as settled: something to actually confirm with the client during this
session rather than carry forward silently as fact.

`InheritedOpenQuestion` and `EngagementStateResponse` back
`GET /api/engagements/{id}/state` (`router.py`): the open questions a prior
meeting left open, plus the engagement's standing `RequirementsState`, both
carried forward for the next meeting to pick up.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.debrief.artifacts.models import RequirementsState


class ReferenceClaim(BaseModel):
    """One context-pack assertion for an engagement, with its verify-with-client flag (PRD FR-3.12).

    `claim_id` is scoped to `engagement_id`, not globally unique on its own —
    two different engagements may each have a claim with the same
    `claim_id`. `verify_with_client` defaults to `False`: a claim starts out
    treated as settled background, and only becomes something to confirm
    live once a user explicitly marks it.
    """

    claim_id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    verify_with_client: bool = False


class InheritedOpenQuestion(BaseModel):
    """One prior meeting's open question, carried onto the engagement's standing state (PRD FR-4.8).

    Mirrors `compiler/bank/recompile.py`'s type of the same name and for the
    same reason: this package stays decoupled from `debrief`'s internals,
    taking the prior meeting's open questions as this small local shape
    instead of importing `debrief/pipeline/models.py`'s `OpenQuestion`.
    """

    text: str = Field(min_length=1)
    impact_rank: int = Field(ge=1)


class EngagementStateResponse(BaseModel):
    """An engagement's inherited open questions plus its standing requirements state (PRD FR-4.8, FR-8.9).

    `inherited_open_questions` is ranked ascending by `impact_rank` — the
    highest-impact question a prior meeting left open comes first, the same
    convention `compiler/bank/recompile.py` and `debrief/artifacts/router.py`'s
    `build_open_questions_router` use. `requirements_state` is `None` for an
    engagement with no prior meetings: there is nothing yet to carry forward,
    not a 404-worthy absence — `router.py`'s route always answers 200.
    """

    engagement_id: str = Field(min_length=1)
    inherited_open_questions: list[InheritedOpenQuestion]
    requirements_state: RequirementsState | None = None
