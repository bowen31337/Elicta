"""Replay metrics package: M1 and M2, broken out per language (PRD §5, T13).

Scores `replay_ratings` rows into `LanguageFigure`s — one per language, never
pooled into a single global M1 or M2. `MetricsPublication` is the entry point
for callers that need to accumulate figures across an engagement's languages
and query them back out; `score_language` is the underlying pure fold for
callers that already have one language's ratings in hand.
"""

from __future__ import annotations

from .models import LanguageFigure, RatedSuggestion
from .publication import MetricsPublication
from .scoring import group_by_language, score_language

__all__ = [
    "LanguageFigure",
    "MetricsPublication",
    "RatedSuggestion",
    "group_by_language",
    "score_language",
]
