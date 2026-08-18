"""Domain types for M1/M2 scoring (PRD §5, NFR-5.7, architecture T13).

Field names mirror the `replay_ratings` table (`useful`, `embarrassing`) so a
rating loaded from that table needs no translation before scoring.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RatedSuggestion:
    """One senior BA's verdict on one suggestion surfaced during a replay run.

    `language` is the language of the replay run the suggestion was surfaced
    in (the `replay_runs.language` the rating's run belongs to), not the
    language of the suggestion text itself — it is what M1 and M2 are
    partitioned by (T13).
    """

    language: str
    useful: bool
    embarrassing: bool

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError("language must not be empty")


@dataclass(frozen=True)
class LanguageFigure:
    """M1 (precision@surfaced) and M2 (embarrassment rate) for one language.

    Both are corpus-level rates over every rating counted for `language`
    (`surfaced_count`), not an average of per-suggestion rates — a language
    with one rated suggestion should not carry the same weight as one with a
    hundred.
    """

    language: str
    surfaced_count: int
    useful_count: int
    embarrassing_count: int

    @property
    def precision_at_surfaced(self) -> float:
        """M1: fraction of surfaced suggestions rated *useful*.

        Zero surfaced suggestions scores 0.0 rather than dividing by zero —
        there is nothing to have been useful.
        """

        if self.surfaced_count == 0:
            return 0.0
        return self.useful_count / self.surfaced_count

    @property
    def embarrassment_rate(self) -> float:
        """M2: fraction of surfaced suggestions rated *would have embarrassed
        me in front of the client*.

        M2 is a gate, not a target (PRD §5): a release candidate for this
        language ships only when this is exactly 0.0.
        """

        if self.surfaced_count == 0:
            return 0.0
        return self.embarrassing_count / self.surfaced_count

    @property
    def clears_m2_gate(self) -> bool:
        """Whether this language's M2 clears the release gate (PRD §5).

        M2 is a gate, not a target: there is no "low enough" nonzero
        embarrassment count that passes, only exactly zero. A language with
        one embarrassing suggestion out of a thousand surfaced fails this
        just as surely as one with one out of one — `embarrassment_rate`
        would make the former look negligible, which is precisely the
        target-style reasoning PRD §5 rules out for M2.
        """

        return self.embarrassing_count == 0
