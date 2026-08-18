"""Publishing M1 and M2 per language, with no single global figure.

Architecture T13: *"the replay harness rating panel ... M1 and M2 become
per-language metrics."* Nothing stops a caller from pooling every language's
ratings into one `score_language` call and quoting the result as *the* M1 or
M2 — exactly what T13 forbids, since a blended figure hides a language
sitting below the 70% M1 bar or carrying a non-zero M2 gate underneath one
that's doing fine. `MetricsPublication` is the type that makes that
impossible to do by accident: it scores each language's ratings
independently and keeps the figures separate. There is deliberately no
method anywhere on this type that folds `LanguageFigure`s together into one
number.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .models import LanguageFigure, RatedSuggestion
from .scoring import score_language


class MetricsPublication:
    """Publishes one M1/M2 figure per language, and only that (T13).

    Every figure is scored and stored independently, keyed by its language —
    there is no operation on this type that combines languages into a single
    blended figure, because T13 forbids quoting one.
    """

    def __init__(self) -> None:
        self._figures: dict[str, LanguageFigure] = {}

    def publish(
        self, language: str, ratings: Iterable[RatedSuggestion]
    ) -> LanguageFigure:
        """Scores `language`'s ratings and publishes its figure.

        Call once per language present in the run. Publishing the same
        language again replaces its prior figure rather than adding a second
        entry.
        """

        figure = score_language(language, ratings)
        self._figures[language] = figure
        return figure

    def figures(self) -> Iterator[LanguageFigure]:
        """Every figure published so far, one entry per language.

        No aggregate is ever available through this type — a caller that
        wants an overall number has to compute it themselves, which T13
        doesn't allow this module to hand them.
        """

        return iter(self._figures.values())

    def figure_for(self, language: str) -> LanguageFigure | None:
        """The figure for one specific language, if it has been published."""

        return self._figures.get(language)

    def languages_failing_m2_gate(self) -> list[LanguageFigure]:
        """Every published figure whose M2 does not clear the release gate.

        Returns the failing `LanguageFigure`s themselves rather than a count
        or a single pass/fail boolean — a release decision needs to name
        which language(s) are blocking, not just that some language is
        (PRD §5, T13). An empty list means every published language clears
        the gate; it does not mean the gate was never checked.
        """

        return [figure for figure in self._figures.values() if not figure.clears_m2_gate]

    def __len__(self) -> int:
        return len(self._figures)

    def is_empty(self) -> bool:
        return not self._figures
