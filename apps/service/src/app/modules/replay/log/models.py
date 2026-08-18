"""Domain types for the replay suggestion-log package."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestionLogRow(BaseModel):
    """One row as written to the `suggestion_log` table.

    Mirrors architecture section 9's row shape exactly: `{timestamp,
    trigger, candidate, score, would_surface}`. One of these is persisted
    per candidate *evaluation*, not per surfaced suggestion — `would_surface`
    is a field on the row rather than a filter on which rows exist, because
    M1 (precision@surfaced) and M2 (embarrassment count) both need the full
    evaluation population to be computed against, not a survivorship-biased
    subset of it.
    """

    timestamp_ms: int
    trigger: str = Field(min_length=1)
    candidate: str = Field(min_length=1)
    score: float
    would_surface: bool
