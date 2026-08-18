"""Domain types for diarizing the retained audio and speaker-tagging each utterance (PRD FR-7.2).

This is the first stage of the debrief pipeline: once the record path (the
`asr-record` module) has produced a full-session transcript, this stage runs
full diarization over the same retained audio and tags every span of that
transcript with which speaker said it. Every later debrief stage — transcript
cleaning, section classification, the BMAD analyst chain, citations — is
built on the `Utterance` this stage produces, so it is defined here rather
than in whichever stage first needed it.

`TranscriptSpan` mirrors the shape `asr-record`'s `TranscriptSegment`
produces (start, end, text), but is its own type rather than an import of
that module's model: plugin modules in this codebase stay decoupled from one
another's internals, communicating through injected callables and
duck-typed inputs rather than direct cross-module imports.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

UNKNOWN_SPEAKER_TAG = "unknown"


class DiarizationStatus(str, Enum):
    """Terminal state of one full diarization run over a session's retained audio."""

    COMPLETE = "complete"
    FAILED = "failed"


class TranscriptSpan(BaseModel):
    """One timed, not-yet-speaker-tagged span of the record-path transcript."""

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str


class SpeakerTurn(BaseModel):
    """One continuous stretch of the retained audio a diarization engine attributed to one speaker."""

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str


class DiarizationOutput(BaseModel):
    """What one diarization engine returns for a full session's retained audio."""

    engine: str
    turns: list[SpeakerTurn]


class Utterance(BaseModel):
    """One durable, speaker-tagged utterance derived from the record-path transcript (PRD FR-7.2).

    `speaker_tag` is never null. PRD FR-7.2 requires full diarization to
    persist a speaker_tag per utterance, so a span the diarization output
    doesn't cover (silence in the diarized turns, or a diarization run that
    produced no turns at all) is tagged `UNKNOWN_SPEAKER_TAG` by
    `tag_span_speaker` rather than left empty — "we couldn't determine the
    speaker" is itself meaningful signal for later debrief stages (and for
    the operator), not a missing value.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker_tag: str


class SessionDiarization(BaseModel):
    """Durable record of one full diarization run over a session's retained audio (PRD FR-7.2).

    Persisted whether the diarization run succeeded or failed, mirroring
    `RecordPathTranscript` in `asr-record`: a session with no diarization
    record at all would be indistinguishable from one that simply hasn't
    been diarized yet, so `status` and `error` make a failed run visible
    instead of silent. `utterances` is empty on a `FAILED` run.
    """

    session_id: str
    status: DiarizationStatus
    engine: str
    utterances: list[Utterance]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class TranscriptCleaningStatus(str, Enum):
    """Terminal state of one transcript-cleaning run over a session's diarized utterances."""

    COMPLETE = "complete"
    FAILED = "failed"


class CleanedUtterance(BaseModel):
    """One `Utterance` with its cleaned text persisted alongside its verbatim original (PRD FR-7.2).

    `verbatim_text` is always the record-path/diarization output untouched;
    `cleaned_text` is what the cleaning engine produced by removing
    disfluencies, correcting vocabulary, and restoring punctuation. Keeping
    both fields on every record — rather than overwriting the transcript in
    place — is what "the cleaned transcript persists alongside the verbatim
    original" means: an operator or later debrief stage can always recover
    exactly what was said, not just the cleaned rendering of it.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    verbatim_text: str
    cleaned_text: str


class SessionTranscriptCleaning(BaseModel):
    """Durable record of one transcript-cleaning run over a session's diarized utterances (PRD FR-7.2).

    Persisted whether the run succeeded or failed, mirroring
    `SessionDiarization`: a session with no cleaning record at all would be
    indistinguishable from one that simply hasn't been cleaned yet, so
    `status` and `error` make a failed run visible instead of silent.
    `utterances` is empty on a `FAILED` run — the verbatim originals still
    live on in `SessionDiarization`, so nothing is lost.
    """

    session_id: str
    status: TranscriptCleaningStatus
    engine: str
    utterances: list[CleanedUtterance]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class AudioDestructionStatus(str, Enum):
    """Terminal state of one attempt to destroy a session's raw retained audio (PRD NFR-2.4)."""

    COMPLETE = "complete"
    FAILED = "failed"


class AudioDestructionEvent(BaseModel):
    """Durable event marking that a session's raw retained audio was destroyed (PRD NFR-2.4).

    NFR-2.4 requires the service discard the raw audio the moment record-path
    transcription and full diarization both complete, retaining it no longer.
    This event is what makes that discard observable: persisted whether the
    deletion succeeded or failed, mirroring `SessionDiarization` and
    `RecordPathTranscript` — a session with no destruction event at all would
    be indistinguishable from one whose audio is still sitting there, so a
    `FAILED` attempt must stay visible rather than silently leaving the raw
    audio retained with no record of why.
    """

    session_id: str
    audio_ref: str
    status: AudioDestructionStatus
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
