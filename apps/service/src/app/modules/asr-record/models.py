"""Domain types for the record-path batch re-transcription (PRD FR-2.5).

The record path re-transcribes the full session after the meeting ends, at
the highest accuracy the engine offers, with no latency constraint — the
opposite trade-off from the live path, which favours low latency over
accuracy (architecture, "Rationale for the split"). These types describe the
result of that batch job, not the live path's incremental output.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TranscriptionStatus(str, Enum):
    """Terminal state of one record-path batch transcription run."""

    COMPLETE = "complete"
    FAILED = "failed"


class TranscriptSegment(BaseModel):
    """One timed span of the full-session transcript."""

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker: str | None = None


class BatchTranscriptionOutput(BaseModel):
    """What a highest-accuracy batch engine returns for one full session.

    `engine` names which engine produced this (PRD FR-2.6 will run two
    independent engines and reconcile; that reconciliation is a separate
    feature — this shape already carries the one field it needs to attribute
    a result to its engine).
    """

    engine: str
    segments: list[TranscriptSegment]
    text: str


class RecordPathTranscript(BaseModel):
    """Durable record-path transcript for one full session (PRD FR-2.5/2.7).

    Persisted whether the batch run succeeded or failed, since a session
    with no record-path transcript at all is indistinguishable from one that
    simply hasn't been re-transcribed yet — `status` and `error` make a
    failed attempt visible instead of silent.
    """

    session_id: str
    status: TranscriptionStatus
    engine: str
    segments: list[TranscriptSegment]
    text: str
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
