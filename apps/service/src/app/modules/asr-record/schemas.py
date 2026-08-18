"""Request DTOs for the record-path re-transcription API (PRD FR-2.5)."""

from pydantic import BaseModel, Field


class RecordPathTranscriptionRequest(BaseModel):
    """Kicks off a batch re-transcription of one full session's recording.

    `audio_ref` points at the full-session recording (e.g. a storage key or
    URI) rather than carrying audio bytes inline — the recording store lives
    outside this package, same reasoning as the injected callables in
    `service.py`.
    """

    audio_ref: str = Field(min_length=1)
