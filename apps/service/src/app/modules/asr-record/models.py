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
    """What one highest-accuracy batch engine returns for one full session.

    `engine` names which engine produced this. PRD FR-2.6 runs two of these
    independently over the same session audio, each persisting its own
    `RecordPathTranscript` tagged by this field; reconciling the two engines'
    output against each other is a separate feature, not done here.
    """

    engine: str
    segments: list[TranscriptSegment]
    text: str


class RecordPathTranscript(BaseModel):
    """Durable record-path transcript for one (session, engine) pair (PRD FR-2.5/2.6/2.7).

    One of these persists per engine configured for the session (PRD FR-2.6
    runs two independent engines), not one per session — `engine` plus
    `session_id` together identify a given transcript. Persisted whether the
    batch run succeeded or failed, since a session with no record-path
    transcript at all is indistinguishable from one that simply hasn't been
    re-transcribed yet — `status` and `error` make a failed attempt visible
    instead of silent.
    """

    session_id: str
    status: TranscriptionStatus
    engine: str
    segments: list[TranscriptSegment]
    text: str
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class TranscriptionJobStatus(str, Enum):
    """Where one record-path transcription job sits in its lifecycle.

    Distinct from `TranscriptionStatus`, which only describes a finished
    batch run's outcome — a job also has a `QUEUED`/`RUNNING` state between
    being accepted and the batch engine actually finishing.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class RecordPathTranscriptionJob(BaseModel):
    """Handle for one meeting's record-path transcription job (PRD FR-2.5).

    Returned immediately when a meeting's full-recording re-transcription is
    accepted, before the (potentially long-running) batch engine call has
    finished — `job_id` is what a caller polls or correlates against later,
    since the transcript itself is not ready yet.
    """

    job_id: str
    meeting_id: str
    status: TranscriptionJobStatus
    created_at: datetime
