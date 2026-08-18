"""Request/response DTOs for the replay run ratings API (feature 26)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SuggestionVerdict(str, Enum):
    """A senior analyst's judgement of one suggestion surfaced during a replay run."""

    USEFUL = "useful"
    TIMELY = "timely"
    EMBARRASSING = "embarrassing"


class SuggestionRatingRequest(BaseModel):
    """One senior analyst rating of a single suggestion from a replay run."""

    suggestion_id: str = Field(min_length=1)
    verdict: SuggestionVerdict


class SuggestionRatingResponse(BaseModel):
    rating_id: str
