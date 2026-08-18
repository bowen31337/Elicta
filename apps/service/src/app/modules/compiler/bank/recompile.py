"""Recompiles one meeting's question bank, weighted toward inherited open questions (PRD FR-4.8).

The engagement-level compile (`POST /api/engagements/{id}/bank/compile`, out
of this feature's footprint) produces the candidate set every meeting in the
engagement recompiles from. This module is the per-meeting recompile step:
it takes that base candidate set plus whatever open questions the prior
meeting raised (already ranked by impact — the same ascending `impact_rank`
convention `build_open_questions_router` in `debrief/artifacts/router.py`
enforces) and produces a fresh `MeetingQuestionBank` in which every inherited
open question outranks every base candidate.

`InheritedOpenQuestion` is a small, local shape rather than an import of
`debrief/pipeline/models.py`'s `OpenQuestion`: this package stays decoupled
from `debrief`'s internals the same way `debrief/pipeline`'s own
`TranscriptSpan` docstring describes for `asr-record` — whoever wires the
per-meeting bank route (out of this feature's footprint) is responsible for
turning the prior meeting's real `OpenQuestion` list into this shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .models import BankCandidate, MeetingQuestionBank

INHERITED_TEMPLATE_SECTION = "carried-forward-open-question"


class InheritedOpenQuestion(BaseModel):
    """One prior meeting's open question, carried in to weight this meeting's recompile (PRD FR-4.8)."""

    text: str
    impact_rank: int = Field(ge=1)


def recompile_meeting_bank(
    meeting_id: str,
    base_candidates: list[BankCandidate],
    inherited_open_questions: list[InheritedOpenQuestion],
    *,
    generated_at: datetime | None = None,
) -> MeetingQuestionBank:
    """Recompile `meeting_id`'s bank, weighting every inherited open question ahead of every base candidate.

    `inherited_open_questions` is expected pre-sorted ascending by
    `impact_rank` (rank 1 = highest impact), the order it already comes back
    from `GET /api/sessions/{id}/open-questions`. Each becomes its own
    `BankCandidate`, assigned `priority` 1..N in that same order, so the
    highest-impact inherited question is always this meeting's single
    highest-priority candidate. Every base candidate keeps its relative
    order but is pushed behind all of them, its own `priority` offset by how
    many open questions were inherited — a meeting that inherits nothing
    recompiles a bank identical in ranking to its base candidates.
    """

    generated_at = generated_at or datetime.now(timezone.utc)

    inherited_candidates = [
        BankCandidate(
            id=f"inherited-open-question-{index}",
            template_section=INHERITED_TEMPLATE_SECTION,
            phrasing=question.text,
            priority=index + 1,
            inherited_from_open_question=True,
        )
        for index, question in enumerate(inherited_open_questions)
    ]

    priority_floor = len(inherited_candidates)
    recompiled_base = [
        candidate.model_copy(update={"priority": priority_floor + candidate.priority})
        for candidate in base_candidates
    ]

    return MeetingQuestionBank(
        meeting_id=meeting_id,
        candidates=[*inherited_candidates, *recompiled_base],
        generated_at=generated_at,
    )
