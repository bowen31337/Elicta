"""Response DTOs for the replay run metrics API (PRD §5, T13).

Both release gates are published here, per language and never blended. M1
(`precision_at_surfaced`) is a target; M2 (`embarrassing_count`) is a gate,
and the two are not shadings of one quality score — a suggestion can be
useless without being embarrassing, and only the second is destructive to a
release.

M2 was left out of this response when the endpoint was first written, on the
grounds that the feature had only been asked to publish M1. That is no longer
tenable now something renders it: a screen that shows "Embarrassing: 0"
because it had no figure to show would report a passing gate for a build that
may well fail it, which is the one direction this number must never be wrong
in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LanguagePrecision(BaseModel):
    """M1 and M2 for one language, over its rated suggestions."""

    language: str = Field(min_length=1)
    surfaced_count: int = Field(ge=0)
    useful_count: int = Field(ge=0)
    precision_at_surfaced: float = Field(ge=0.0, le=1.0)
    embarrassing_count: int = Field(default=0, ge=0)
    clears_m2_gate: bool = True


class ReplayRunMetricsResponse(BaseModel):
    """M1 and M2, broken out per language, for one replay run (T13: never blended)."""

    run_id: str = Field(min_length=1)
    languages: list[LanguagePrecision]
