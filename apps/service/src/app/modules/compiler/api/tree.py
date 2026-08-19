"""Groups an engagement's compiled candidate set into a reviewable tree by template section (PRD FR-4.5, FR-4.8).

FR-4.5 is the phase 0 deliverable this produces: the compiled bank presented
to the operator pre-meeting as a tree they can review, reorder and prune
(pruning and editing are `build_bank_candidates_router`'s two endpoints).

The engagement-level compile (`POST /api/engagements/{id}/bank/compile`, out
of this feature's footprint) produces the flat, priority-ordered candidate
set this module groups. Unlike `recompile.py`'s per-meeting recompile, this
step doesn't rerank anything -- it only reshapes an already priority-ordered
list into branches a reviewer can act on, one per `template_section`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .models import BankCandidate, EngagementQuestionBank, QuestionBankSection


def build_question_bank_tree(
    engagement_id: str,
    candidates: list[BankCandidate],
    *,
    generated_at: datetime | None = None,
) -> EngagementQuestionBank:
    """Group `candidates` into sections, preserving candidate order and each section's first-seen order.

    `candidates` is expected pre-sorted ascending by `priority`, the same
    invariant `recompile_meeting_bank` produces its output under. Grouping
    doesn't re-sort within a section: a section's candidates come out in the
    same relative order they arrived in, and sections themselves are ordered
    by whichever of their candidates appeared first -- so an engagement's
    highest-priority candidate's section always renders as the tree's first
    branch.
    """

    generated_at = generated_at or datetime.now(UTC)

    sections: dict[str, list[BankCandidate]] = {}
    for candidate in candidates:
        sections.setdefault(candidate.template_section, []).append(candidate)

    return EngagementQuestionBank(
        engagement_id=engagement_id,
        sections=[
            QuestionBankSection(template_section=section, candidates=section_candidates)
            for section, section_candidates in sections.items()
        ],
        generated_at=generated_at,
    )
