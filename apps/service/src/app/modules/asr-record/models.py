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


class AlignedSpan(BaseModel):
    """One time-aligned span comparing both engines' output over the same interval.

    `reference_text`/`other_text` are what each engine produced for this
    span — `other_text` is the concatenation of whatever the other engine's
    segments overlap this interval, since the two engines rarely agree on
    exact segment boundaries even when they agree on the words. `agreement_score`
    is the confidence signal this feature exists to produce: 1.0 means the
    two engines' normalized wording matched exactly here, 0.0 means they
    shared no words at all (including the case where one engine transcribed
    silence where the other transcribed speech) — it is never left null,
    since a low or zero score is itself meaningful signal, not a missing value.

    `is_divergent` is set alongside `agreement_score` by `alignment.py`
    (PRD FR-2.8) whenever that score falls below the divergence threshold.
    It is a separate persisted field rather than something a reader
    recomputes from `agreement_score` at display time, so every disagreeing
    span is flagged for operator review during debrief instead of the
    service silently picking one engine's wording as the winner.
    """

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    reference_engine: str
    reference_text: str
    other_engine: str
    other_text: str
    agreement_score: float = Field(ge=0, le=1)
    is_divergent: bool


class SessionAlignment(BaseModel):
    """Durable record of aligning one session's two record-path transcripts (PRD FR-2.6 follow-on).

    Persisted once both engines configured for a session have produced a
    `COMPLETE` `RecordPathTranscript` — reconciling the two engines' output
    only means something once both independent results exist, so this is a
    separate artifact from either transcript rather than a field on one of them.
    """

    session_id: str
    reference_engine: str
    other_engine: str
    spans: list[AlignedSpan]
    computed_at: datetime


class RecordPathSourceReference(BaseModel):
    """Pins one artifact claim, citation, or coverage decision to a record-path span (PRD FR-2.7).

    Every requirements claim, citation, and coverage decision the debrief
    artifacts (PRD FR-8) produce must trace back to this batch,
    highest-accuracy transcript rather than the live path's interim, lower-
    accuracy output — `cite_record_path_span` in `citation.py` is the only
    way to construct one, and it refuses to build a reference for any span
    the persisted record-path transcript doesn't actually cover. That makes
    it structurally impossible for an artifact to carry a reference sourced
    from the live transcript: this type only ever comes from a `COMPLETE`
    `RecordPathTranscript`, never from the incremental live-path output.

    `quoted_text` is the record-path wording for the referenced span, kept
    alongside the pointer rather than requiring a reader to re-fetch and
    re-slice the transcript to see what was actually cited. `transcript_completed_at`
    records when the record-path batch run that grounds this reference
    finished, so a reviewer can tell which batch run backs a given claim.
    """

    session_id: str
    engine: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    quoted_text: str
    transcript_completed_at: datetime


class RecordPathTranscriptionJob(BaseModel):
    """Handle for one meeting's record-path transcription job (PRD FR-2.5).

    Returned immediately when a meeting's full-recording re-transcription is
    accepted, before the (potentially long-running) batch engine call has
    finished — `job_id` is what a caller polls or correlates against later,
    since the transcript itself is not ready yet.

    `engine_lineages` records both engine identifiers configured for this run
    on the job itself, not just on each engine's own `RecordPathTranscript`
    (PRD FR-2.6). Reconciling the two engines' output only tells you anything
    if they're actually independent — sharing training data would make
    agreement between them meaningless — so the run record needs to show
    which two lineages were used together without having to join across the
    separate per-engine transcripts, which may not both exist yet (one may
    still be running, or may have failed before producing one).
    """

    job_id: str
    meeting_id: str
    status: TranscriptionJobStatus
    created_at: datetime
    engine_lineages: list[str]
