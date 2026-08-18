"""The single audited egress chokepoint for the service tier (architecture
§8, "Egress control"; PRD NFR-2.7).

Architecture §8 splits NFR-2.7's "single audited chokepoint" into two hops:
one in the core for device-originated egress, and this one in the service
tier for every call the service fans out to an external processor. Both are
required to route through one class rather than calling a transport client
directly — that is the only way "every path out of the system passes
through a logged chokepoint" holds as a structural guarantee rather than a
call-site convention.

The actual network transport and the actual `egress_log` persistence stay
out of this package (supplied via `EgressTransport` and `EgressLogSink`).
What lives here is the invariant itself: `EgressChokepoint.send` always
writes exactly one `EgressLogRow`, whether the underlying request succeeds
or fails.
"""

from __future__ import annotations

from app.core.egress.clock import EgressClock
from app.core.egress.errors import EgressLogError, EgressTransportError
from app.core.egress.models import EgressLogRow, ProcessorRequest, ProcessorSuccess
from app.core.egress.sink import EgressLogSink
from app.core.egress.transport import EgressTransport


class EgressChokepoint:
    """The single chokepoint every service-originated call to an external
    processor must be routed through (PRD NFR-2.7).

    Holding this as the only way to reach `EgressTransport` is what makes
    "every processor call is audited" a structural guarantee instead of a
    call-site convention.
    """

    def __init__(
        self,
        clock: EgressClock,
        transport: EgressTransport,
        sink: EgressLogSink,
    ) -> None:
        self._clock = clock
        self._transport = transport
        self._sink = sink

    def send(self, request: ProcessorRequest) -> ProcessorSuccess:
        """Executes `request` and unconditionally persists an `egress_log`
        row for it before returning.

        The row is written whether the request succeeded or failed. A
        failure to persist it propagates as `EgressLogError` rather than
        being swallowed — an egress that can't be audited is the exact
        failure this chokepoint exists to prevent.
        """

        success: ProcessorSuccess | None = None
        error: EgressTransportError | None = None
        try:
            success = self._transport.execute(request)
        except EgressTransportError as exc:
            error = exc

        byte_count = request.body_bytes + (success.response_bytes if success else 0)
        row = EgressLogRow(
            timestamp_ms=self._clock.now_ms(),
            processor_name=request.processor_name,
            byte_count=byte_count,
            success=error is None,
            error=str(error) if error is not None else None,
        )

        self._sink.record(row)

        if error is not None:
            raise error
        assert success is not None
        return success
