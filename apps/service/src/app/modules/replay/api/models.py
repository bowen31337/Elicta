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


class StartReplayRunRequest(BaseModel):
    """A request to start a replay run against an already-uploaded recording.

    `language` is the language the run is conducted in, and it is carried
    here because M1 (precision@surfaced) and M2 (embarrassment rate) are
    partitioned by it (architecture T13) -- a rating has no language of its
    own, it inherits the run's. It defaults rather than being required so
    that existing callers keep working, but a run in another language must
    say so: scoring a Portuguese run under `en` does not make the figure
    wrong by a little, it files it under the wrong gate entirely.
    """

    recording_id: str = Field(min_length=1)
    language: str = Field(default="en", min_length=1)


class StartReplayRunResponse(BaseModel):
    """Acknowledgement that a replay run has been queued."""

    run_id: str = Field(min_length=1)


class ReplayRunStatus(str, Enum):
    """Lifecycle state of a replay run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReplayRunStatusResponse(BaseModel):
    """Progress snapshot for one replay run."""

    run_id: str = Field(min_length=1)
    status: ReplayRunStatus
    progress: float = Field(ge=0.0, le=1.0)
    suggestion_count: int = Field(ge=0)
