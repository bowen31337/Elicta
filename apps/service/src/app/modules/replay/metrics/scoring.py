"""Folds one language's ratings into its M1/M2 figure (PRD §5, T13).

Partition ratings by language before calling `score_language`, once per
partition — pooling ratings from more than one language into a single call
here would produce exactly the blended global figure T13 forbids.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import LanguageFigure, RatedSuggestion


def score_language(language: str, ratings: Iterable[RatedSuggestion]) -> LanguageFigure:
    """Scores every rating in `ratings` as belonging to `language`.

    A rating's own `.language` is ignored here on purpose: the caller has
    already partitioned by language (typically via `group_by_language`), and
    re-checking each rating against `language` would just be a slower way of
    doing the same partitioning twice.
    """

    surfaced_count = 0
    useful_count = 0
    embarrassing_count = 0

    for rating in ratings:
        surfaced_count += 1
        if rating.useful:
            useful_count += 1
        if rating.embarrassing:
            embarrassing_count += 1

    return LanguageFigure(
        language=language,
        surfaced_count=surfaced_count,
        useful_count=useful_count,
        embarrassing_count=embarrassing_count,
    )


def group_by_language(
    ratings: Iterable[RatedSuggestion],
) -> dict[str, list[RatedSuggestion]]:
    """Partitions `ratings` by `.language`, preserving each group's order."""

    grouped: dict[str, list[RatedSuggestion]] = {}
    for rating in ratings:
        grouped.setdefault(rating.language, []).append(rating)
    return grouped
