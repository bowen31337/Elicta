"""Domain types for the service-tier egress chokepoint (PRD NFR-2.7, architecture §8)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProcessorRequest(BaseModel):
    """A request about to leave the service through the chokepoint.

    ``processor_name`` identifies which external processor this call fans
    out to (e.g. a transcription or diarization vendor) — it is the value
    that ends up in the audit row's ``processor_name`` column, so callers
    should pass a stable identifier rather than a free-form description.
    """

    processor_name: str
    destination: str
    body_bytes: int = Field(ge=0)


class ProcessorSuccess(BaseModel):
    """A successful transport outcome."""

    response_bytes: int = Field(ge=0)


class EgressLogRow(BaseModel):
    """One row as written to the `egress_log` table.

    ``byte_count`` is the total bytes moved for this call: the request body
    sent, plus the response body received when the call succeeded. A failed
    call still counts the bytes that were sent before it failed.
    """

    timestamp_ms: int
    processor_name: str
    byte_count: int = Field(ge=0)
    success: bool
    error: str | None = None
