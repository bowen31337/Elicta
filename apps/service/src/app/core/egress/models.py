"""Domain types for the service-tier egress chokepoint (PRD NFR-2.7, architecture §8)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProcessorRequest(BaseModel):
    """A request about to leave the service through the chokepoint.

    ``processor_name`` identifies which external processor this call fans
    out to (e.g. a transcription or diarization vendor) — it is the value
    that ends up in the audit row's ``processor_name`` column, so callers
    should pass a stable identifier rather than a free-form description.

    ``engagement_id`` identifies which engagement this call is made on
    behalf of. The chokepoint uses it to look up that engagement's pinned
    processing region (PRD NFR-2.2) rather than accepting a region on the
    request itself — the pin lives with the engagement, not with each call,
    so a call can't drift to a different region than the one already
    agreed with the client.

    ``destination`` is restricted to ``https://`` so that "every request
    sends over TLS only" is a guarantee this type enforces on construction,
    rather than something every caller has to remember to check.

    ``vendor_params`` carries the vendor-specific request parameters (e.g.
    Deepgram's ``mip_opt_out``) that ride alongside the request body.
    `RetentionEnforcingEgressTransport` reads and overwrites entries here
    to force vendor-side retention to zero (PRD NFR-2.3); callers may also
    populate it directly for parameters unrelated to retention.
    """

    processor_name: str
    engagement_id: str
    destination: str
    body_bytes: int = Field(ge=0)
    vendor_params: dict[str, Any] = Field(default_factory=dict)

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

    ``engagement_id`` identifies which engagement the call was made on
    behalf of. It is always present — even for the regionless row of a call
    the chokepoint refused outright — since the request carries it before
    the region lookup happens, and it is what the audit log at
    `GET /api/audit/egress` filters rows by.

    ``region`` is the processing region pinned for the call's engagement
    (PRD NFR-2.2), recorded on every row so residency can be audited after
    the fact rather than only enforced at call time. It is ``None`` only
    for the row of a call the chokepoint refused outright because its
    engagement had no region pinned — such a call never reaches the
    transport, so there is no region to record.

    ``byte_count`` is the total bytes moved for this call: the request body
    sent, plus the response body received when the call succeeded. A failed
    call still counts the bytes that were sent before it failed.
    """

    timestamp_ms: int
    engagement_id: str
    processor_name: str
    region: str | None = None
    byte_count: int = Field(ge=0)
    success: bool
    error: str | None = None
