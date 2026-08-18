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
