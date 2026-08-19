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
from app.core.egress.errors import (
    EgressRegionError,
    EgressTransportError,
)
from app.core.egress.models import EgressLogRow, ProcessorRequest, ProcessorSuccess
from app.core.egress.region import EngagementRegionRegistry
from app.core.egress.sink import EgressLogSink
from app.core.egress.transport import EgressTransport


class EgressChokepoint:
    """The single chokepoint every service-originated call to an external
    processor must be routed through (PRD NFR-2.7).

    Holding this as the only way to reach `EgressTransport` is what makes
    "every processor call is audited" a structural guarantee instead of a
    call-site convention. It also pins the processing region for the
    request's engagement (PRD NFR-2.2): the region is looked up here, from
    `EngagementRegionRegistry`, rather than trusted from the caller, so it
    can't drift from the region actually agreed with the client.
    """

    def __init__(
        self,
        clock: EgressClock,
        transport: EgressTransport,
        sink: EgressLogSink,
        regions: EngagementRegionRegistry,
    ) -> None:
        self._clock = clock
        self._transport = transport
        self._sink = sink
        self._regions = regions

    def send(self, request: ProcessorRequest) -> ProcessorSuccess:
        """Executes `request` and unconditionally persists an `egress_log`
        row for it before returning.

        The row is written whether the request succeeded or failed. A
        failure to persist it propagates as `EgressLogError` rather than
        being swallowed — an egress that can't be audited is the exact
        failure this chokepoint exists to prevent.

        The request's engagement must already have a pinned region. If it
        doesn't, the call never reaches the transport at all — it is
        recorded as a failed, regionless row and `EgressRegionError` is
        raised — since sending without a pinned region is the residency
        violation NFR-2.2 exists to prevent.
        """

        region = self._regions.region_for(request.engagement_id)

        success: ProcessorSuccess | None = None
        error: Exception | None = None
        if region is None:
            error = EgressRegionError(
                f"no processing region pinned for engagement "
                f"{request.engagement_id!r}"
            )
        else:
            try:
                success = self._transport.execute(request)
            except EgressTransportError as exc:
                error = exc

        sent_bytes = request.body_bytes if region is not None else 0
        byte_count = sent_bytes + (success.response_bytes if success else 0)
        row = EgressLogRow(
            timestamp_ms=self._clock.now_ms(),
            engagement_id=request.engagement_id,
            processor_name=request.processor_name,
            region=region,
            byte_count=byte_count,
            success=error is None,
            error=str(error) if error is not None else None,
        )

        self._sink.record(row)

        if error is not None:
            raise error
        assert success is not None
        return success
