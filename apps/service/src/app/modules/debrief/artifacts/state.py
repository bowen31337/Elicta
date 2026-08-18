"""Merges one meeting's confirmed requirements and decisions into the engagement's standing state (PRD FR-8.9).

`build_coverage_matrix` (PRD FR-8.2) already turns one meeting's section
classification into a `RequirementsCoverageMatrix`, and `run_bmad_analyst_chain`
(PRD FR-4.1, FR-8) already turns its classified utterances into a
`BmadArtifactSet`. This is the last stage of the debrief pipeline (PRD G4):
it folds both of those into whatever `RequirementsState` the engagement
already had — from every meeting before this one — into an updated state,
and persists it via an injected `save`, mirroring every other stage in this
package (no durable store exists yet in this codebase).

Unlike `RequirementsCoverageMatrix` or `SessionBmadAnalystChain`, a
`RequirementsState` is engagement-scoped rather than meeting-scoped: there is
exactly one row per engagement, and "carried into the next meeting" is
realized simply by upserting it — whichever meeting reads the engagement's
state next sees the latest merge, with no explicit "next meeting" pointer to
resolve.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.modules.debrief.pipeline.models import BmadArtifactSet

from .models import (
    ConfirmedRequirement,
    CoverageMatrixStatus,
    FillState,
    RequirementsCoverageMatrix,
    RequirementsContradiction,
    RequirementsState,
)

SaveRequirementsState = Callable[[RequirementsState], Awaitable[None]]


def _confirmed_requirements_from_matrix(matrix: RequirementsCoverageMatrix) -> list[ConfirmedRequirement]:
    """Turn every `FILLED` entry of a `COMPLETE` matrix into a `ConfirmedRequirement` (PRD FR-8.9).

    A `FAILED` matrix contributes nothing — it carries no entries at all
    (`build_coverage_matrix` never persists a partial one), so there is
    nothing new this meeting demonstrated to confirm.
    """

    if matrix.status != CoverageMatrixStatus.COMPLETE:
        return []

    return [
        ConfirmedRequirement(section_key=entry.section_key, title=entry.title, citations=entry.citations)
        for entry in matrix.entries
        if entry.fill_state == FillState.FILLED
    ]


def _quoted_text(requirement: ConfirmedRequirement) -> str:
    if not requirement.citations:
        raise ValueError(f"confirmed requirement for section {requirement.section_key!r} has no citation")
    return requirement.citations[0].quoted_text


def _merge_confirmed_requirements(
    previous: list[ConfirmedRequirement], new: list[ConfirmedRequirement]
) -> tuple[list[ConfirmedRequirement], list[RequirementsContradiction]]:
    """Fold `new` into `previous` by section, flagging any section confirmed differently (PRD FR-8.9).

    A section this meeting confirms for the first time is simply added. A
    section the engagement already had confirmed, reconfirmed here with the
    same quoted citation, just keeps the existing entry unchanged. A section
    reconfirmed with a *different* quoted citation is a contradiction: this
    meeting's confirmation still wins going forward — the standing state
    always reflects what the engagement's most recent meeting said — but the
    conflict is recorded rather than silently overwritten.
    """

    merged_by_section = {requirement.section_key: requirement for requirement in previous}
    contradictions: list[RequirementsContradiction] = []

    for requirement in new:
        existing = merged_by_section.get(requirement.section_key)
        if existing is not None and _quoted_text(existing) != _quoted_text(requirement):
            contradictions.append(
                RequirementsContradiction(
                    section_key=requirement.section_key,
                    previous_citation=existing.citations[0],
                    new_citation=requirement.citations[0],
                )
            )
        merged_by_section[requirement.section_key] = requirement

    return list(merged_by_section.values()), contradictions


async def merge_requirements_state_forward(
    engagement_id: str,
    previous_state: RequirementsState | None,
    matrix: RequirementsCoverageMatrix,
    artifacts: BmadArtifactSet,
    save: SaveRequirementsState,
    *,
    merged_at: datetime | None = None,
) -> RequirementsState:
    """Merge one meeting's coverage matrix and BMAD artifacts into the engagement's standing state (PRD FR-8.9).

    `previous_state` is `None` for an engagement's first meeting — there is
    nothing yet to carry forward, so the merge starts from empty
    `confirmed_requirements`/`contradictions`/`decisions`. Every later meeting
    passes the state `merge_requirements_state_forward` last persisted for
    this engagement, so confirmed requirements and contradictions accumulate
    section-by-section (`_merge_confirmed_requirements`) and decisions
    accumulate meeting-by-meeting, rather than each meeting's merge only ever
    reflecting itself. The merged state is what persists against the
    engagement — this function's only side effect — and is also what it
    returns.
    """

    merged_at = merged_at or datetime.now(timezone.utc)

    previous_confirmed = previous_state.confirmed_requirements if previous_state else []
    previous_contradictions = previous_state.contradictions if previous_state else []
    previous_decisions = previous_state.decisions if previous_state else []

    new_confirmed = _confirmed_requirements_from_matrix(matrix)
    confirmed_requirements, new_contradictions = _merge_confirmed_requirements(previous_confirmed, new_confirmed)

    result = RequirementsState(
        engagement_id=engagement_id,
        confirmed_requirements=confirmed_requirements,
        contradictions=[*previous_contradictions, *new_contradictions],
        decisions=[*previous_decisions, *artifacts.decisions],
        updated_at=merged_at,
    )
    await save(result)
    return result
