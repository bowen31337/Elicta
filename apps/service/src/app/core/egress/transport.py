"""Sends the actual request to the external processor.

Left as a `Protocol` so this package never depends on a concrete HTTP client
and the chokepoint's logging invariant is testable without a real network.
Implementations should raise `EgressTransportError` on failure rather than
returning a sentinel, so the chokepoint has exactly one failure signal to
catch.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.egress.errors import EgressTransportError
from app.core.egress.models import ProcessorRequest, ProcessorSuccess
from app.core.egress.pinning import ProcessorPinRegistry


@runtime_checkable
class EgressTransport(Protocol):
    def execute(self, request: ProcessorRequest) -> ProcessorSuccess: ...


class PinningEgressTransport:
    """Wraps another `EgressTransport` and enforces certificate pinning for
    processors whose enterprise gateway supports it (PRD NFR-2.7).

    `ProcessorRequest.destination` is already restricted to `https://` at
    the model level, so every call the wrapped transport makes is already
    over TLS; this layer adds the stricter check that the leaf certificate
    presented during the handshake also matches a pinned fingerprint, for
    the subset of processors that have one registered via
    `ProcessorPinRegistry`.

    A pinned processor whose inner transport doesn't report a certificate
    is treated as a pin failure rather than silently passed through — an
    unverifiable pin is not a passing pin.
    """

    def __init__(self, inner: EgressTransport, pins: ProcessorPinRegistry) -> None:
        self._inner = inner
        self._pins = pins

    def execute(self, request: ProcessorRequest) -> ProcessorSuccess:
        success = self._inner.execute(request)

        pin = self._pins.pin_for(request.processor_name)
        if pin is None:
            return success

        if success.peer_certificate_sha256 is None or not pin.matches(
            success.peer_certificate_sha256
        ):
            raise EgressTransportError(
                f"certificate pin mismatch for {request.processor_name!r}"
            )

        return success
