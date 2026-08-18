"""Suppresses solution-shaped and epic-shaped candidates while an engagement is still at discovery stage (PRD FR-4.6).

FR-4.6 is explicit: discovery-stage banks stay in problem space, and
solution-shaped or epic-shaped questions are suppressed "before the
requirements template calls for them." No engagement-stage or
candidate-shape taxonomy exists elsewhere in this codebase yet (unlike
`DocumentStatus` in `engagement/documents/models.py`, which
`hypothesis_verification.py` reuses directly) -- `EngagementStage` and
`CandidateShape` (`.models`) are therefore net-new, local concepts. Whoever
classifies a compiled `BankCandidate`'s shape (out of this feature's
footprint -- presumably the BMAD analyst pass from FR-4.1/FR-4.2 that tags
candidates with a target template section) is responsible for handing this
technique `ShapedCandidate`s in that shape, the same handoff
`HypothesisDocumentClaim` describes for claim extraction.

`suppress_out_of_stage_candidates` is that filter pass: at
`EngagementStage.DISCOVERY` it drops every `SOLUTION`- or `EPIC`-shaped
candidate and reports how many of each were dropped, so a caller can
surface "N solution-shaped questions suppressed" rather than silently
shrinking the bank. At any other stage nothing is suppressed -- the
requirements template has already started calling for solution- and
epic-shaped questions, so this pass is a no-op.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..bank.models import BankCandidate
from .models import CandidateShape, EngagementStage, ShapedCandidate

SUPPRESSED_SHAPES = frozenset({CandidateShape.SOLUTION, CandidateShape.EPIC})


class StageSuppressionResult(BaseModel):
    """The candidates that survived stage suppression, plus how many of each suppressed shape were dropped (PRD FR-4.6)."""

    candidates: list[BankCandidate]
    suppressed_solution_count: int = Field(ge=0)
    suppressed_epic_count: int = Field(ge=0)


def suppress_out_of_stage_candidates(
    shaped_candidates: list[ShapedCandidate], stage: EngagementStage
) -> StageSuppressionResult:
    """Drop solution- and epic-shaped candidates while `stage` is `DISCOVERY`, counting each shape dropped.

    Candidates keep their original relative order and `priority` -- this
    pass only filters, it does not re-rank. Outside `DISCOVERY`, every
    candidate passes through untouched and both counts are zero.
    """

    if stage != EngagementStage.DISCOVERY:
        return StageSuppressionResult(
            candidates=[shaped.candidate for shaped in shaped_candidates],
            suppressed_solution_count=0,
            suppressed_epic_count=0,
        )

    kept: list[BankCandidate] = []
    suppressed_solution_count = 0
    suppressed_epic_count = 0

    for shaped in shaped_candidates:
        if shaped.shape == CandidateShape.SOLUTION:
            suppressed_solution_count += 1
        elif shaped.shape == CandidateShape.EPIC:
            suppressed_epic_count += 1
        else:
            kept.append(shaped.candidate)

    return StageSuppressionResult(
        candidates=kept,
        suppressed_solution_count=suppressed_solution_count,
        suppressed_epic_count=suppressed_epic_count,
    )
