"""Sends the actual request to the external processor.

Left as a `Protocol` so this package never depends on a concrete HTTP client
and the chokepoint's logging invariant is testable without a real network.
Implementations should raise `EgressTransportError` on failure rather than
returning a sentinel, so the chokepoint has exactly one failure signal to
catch.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.egress.models import ProcessorRequest, ProcessorSuccess


@runtime_checkable
class EgressTransport(Protocol):
    def execute(self, request: ProcessorRequest) -> ProcessorSuccess: ...
