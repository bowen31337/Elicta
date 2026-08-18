"""Domain types for the service-tier egress chokepoint (PRD NFR-2.7, architecture §8)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProcessorRequest(BaseModel):
    """A request about to leave the service through the chokepoint.

    ``processor_name`` identifies which external processor this call fans
    out to (e.g. a transcription or diarization vendor) — it is the value
    that ends up in the audit row's ``processor_name`` column, so callers
    should pass a stable identifier rather than a free-form description.

    ``destination`` is restricted to ``https://`` so that "every request
    sends over TLS only" is a guarantee this type enforces on construction,
    rather than something every caller has to remember to check.
    """

    processor_name: str
    destination: str
    body_bytes: int = Field(ge=0)

    @field_validator("destination")
    @classmethod
    def _destination_must_use_tls(cls, value: str) -> str:
        if not value.lower().startswith("https://"):
            raise ValueError(
                f"destination must use TLS (https://): {value!r}"
            )
        return value


class ProcessorSuccess(BaseModel):
    """A successful transport outcome.

    ``peer_certificate_sha256`` is the SHA-256 fingerprint of the leaf TLS
    certificate the transport observed during the handshake, when the
    concrete transport is able to report one. It is ``None`` for processors
    whose transport doesn't surface this (e.g. no certificate was presented
    for pinning purposes) — `PinningEgressTransport` treats that as a pin
    failure for any processor that has a pin registered.
    """

    response_bytes: int = Field(ge=0)
    peer_certificate_sha256: str | None = None


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
