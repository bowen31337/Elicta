"""Wire and domain shapes for operator enrolment (PRD FR-1.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EnrolmentRequest(BaseModel):
    """One enrolment sample, in the format the whole system moves audio in.

    Base64 linear16, 16kHz, mono — the same shape `POST /audio-chunk` takes and
    the same shape the panel's `pcm.ts` produces, so the capture screen needs
    no second conversion to enrol.
    """

    pcm: str = Field(min_length=1)


class OperatorVoiceprint(BaseModel):
    """The enrolled print, as persisted to `operator_voiceprints`.

    `embedding` is base64 rather than raw bytes because this model is stored
    through the JSON-dumping path every other durable collection uses, and raw
    bytes do not survive it. The column underneath is still binary.
    """

    operator_id: str
    embedding: str
    embedding_model: str
    sample_duration_ms: int
    enrolled_at: datetime


class VoiceprintStatus(BaseModel):
    """What the capture screen is told about the enrolment.

    Never the embedding, on the same reasoning the settings surface never
    returns a secret: an operator's voiceprint is biometric material, this is a
    read anyone who can reach the API can make, and nothing on the screen has
    any use for the bytes. The status answers "am I enrolled, with how much
    audio, by which model, and when" — which is everything the screen shows.

    `max_sample_seconds` and `min_sample_seconds` come from here rather than
    being written into the panel, so the cap the UI counts down to is the cap
    the service actually enforces.
    """

    enrolled: bool
    sample_seconds: float | None = None
    embedding_model: str | None = None
    enrolled_at: datetime | None = None
    max_sample_seconds: int
    min_sample_seconds: int
    #: Whether the enrolled print can still be compared against live audio. A
    #: print from a retired embedder reads as enrolled and verifies nothing,
    #: and a screen that showed only "Enrolled" would hide that completely.
    usable: bool = False
