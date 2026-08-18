"""Response DTOs for the replay run metrics API (PRD §5, T13).

Only M1 (precision@surfaced) is exposed here — this feature is scoped to
that one metric. `LanguageFigure` already carries M2's counts too, but a
response schema that surfaced them here would be committing this endpoint's
shape to a metric this feature was never asked to publish.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LanguagePrecision(BaseModel):
    """M1 for one language: precision@surfaced over its rated suggestions."""

    language: str = Field(min_length=1)
    surfaced_count: int = Field(ge=0)
    useful_count: int = Field(ge=0)
    precision_at_surfaced: float = Field(ge=0.0, le=1.0)


class ReplayRunMetricsResponse(BaseModel):
    """M1, broken out per language, for one replay run (T13: never blended)."""

    run_id: str = Field(min_length=1)
    languages: list[LanguagePrecision]
