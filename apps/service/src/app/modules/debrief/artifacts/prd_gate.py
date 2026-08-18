"""Gates full PRD generation on requirements coverage across an engagement's meetings (PRD FR-8.10).

FR-8.10's rationale is explicit: one discovery meeting does not contain a
PRD, and generating one anyway produces a confident, hallucinated document
the operator then has to un-believe — worse than no document at all.
`summarize_engagement_coverage` aggregates the `RequirementsCoverageMatrix`
(PRD FR-8.2, from `matrix.py`) each of an engagement's meetings has built into
one `EngagementCoverageSummary`, treating a taxonomy section as covered the
moment *any* meeting has filled it — coverage is meant to accumulate across
meetings (PRD FR-8.9), not be re-demonstrated by a single call.
`require_prd_generation_coverage` is the gate itself: it raises
`PrdGenerationRefused`, carrying the summary and an explanatory message, for
anything a caller can turn into a 409 rather than letting a request for the
full PRD reach whatever actually generates it.
"""

from __future__ import annotations

from .models import (
    CoverageGapSection,
    CoverageMatrixStatus,
    EngagementCoverageSummary,
    FillState,
    RequirementsCoverageMatrix,
)

DEFAULT_PRD_COVERAGE_THRESHOLD = 1.0


def summarize_engagement_coverage(matrices: list[RequirementsCoverageMatrix]) -> EngagementCoverageSummary:
    """Aggregate every meeting's coverage matrix into one engagement-wide coverage summary (PRD FR-8.10).

    Only `COMPLETE` matrices contribute — a `FAILED` matrix (from
    `build_coverage_matrix`) carries no entries and would only ever suppress
    coverage a meeting actually demonstrated, never add any. The known
    taxonomy is derived from whatever section keys the contributing matrices
    actually mention (every `COMPLETE` matrix already lists one entry per
    known section, per `build_coverage_matrix`), so a section is `covered`
    once any single meeting filled it, even if another meeting left it
    `EMPTY` or never mentioned it at all.
    """

    sections: dict[str, str] = {}
    filled_keys: set[str] = set()

    for matrix in matrices:
        if matrix.status != CoverageMatrixStatus.COMPLETE:
            continue
        for entry in matrix.entries:
            sections.setdefault(entry.section_key, entry.title)
            if entry.fill_state == FillState.FILLED:
                filled_keys.add(entry.section_key)

    total_sections = len(sections)
    covered_sections = len(filled_keys)
    coverage_ratio = covered_sections / total_sections if total_sections else 0.0
    missing_sections = [
        CoverageGapSection(section_key=key, title=title)
        for key, title in sections.items()
        if key not in filled_keys
    ]

    return EngagementCoverageSummary(
        meeting_count=len(matrices),
        total_sections=total_sections,
        covered_sections=covered_sections,
        coverage_ratio=coverage_ratio,
        missing_sections=missing_sections,
    )


class PrdGenerationRefused(Exception):
    """Raised when an engagement's cross-meeting coverage does not clear the PRD FR-8.10 threshold.

    Carries the `EngagementCoverageSummary` and the `threshold` it was
    checked against so a caller — an HTTP router mapping this to 409, or any
    other caller — can render an explanatory message without recomputing
    coverage itself. The message names the current coverage ratio, the
    threshold it fell short of, and every still-missing section by title, so
    the 409 body is self-explanatory rather than a bare refusal.
    """

    def __init__(self, summary: EngagementCoverageSummary, threshold: float) -> None:
        self.summary = summary
        self.threshold = threshold
        missing_titles = ", ".join(section.title for section in summary.missing_sections) or "none"
        super().__init__(
            f"requirements coverage across {summary.meeting_count} meeting(s) is "
            f"{summary.coverage_ratio:.0%} ({summary.covered_sections}/{summary.total_sections} sections), "
            f"below the {threshold:.0%} threshold PRD FR-8.10 requires for full PRD generation; "
            f"missing sections: {missing_titles}"
        )


def require_prd_generation_coverage(
    matrices: list[RequirementsCoverageMatrix], *, threshold: float = DEFAULT_PRD_COVERAGE_THRESHOLD
) -> EngagementCoverageSummary:
    """Return the engagement's coverage summary if it clears `threshold`, else raise `PrdGenerationRefused`.

    An engagement with no known taxonomy sections at all — no meeting has
    ever completed classification — is refused regardless of `threshold`:
    a vacuous 0/0 ratio is not evidence of sufficient coverage, it is
    evidence that coverage hasn't been assessed yet.
    """

    summary = summarize_engagement_coverage(matrices)
    if summary.total_sections == 0 or summary.coverage_ratio < threshold:
        raise PrdGenerationRefused(summary, threshold)
    return summary
