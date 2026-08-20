"""Auditing the calls the service makes to an external processor (PRD NFR-2.7).

`EgressChokepoint` next door holds the same invariant for a *synchronous*
transport: exactly one `EgressLogRow` per call, written whether the call
succeeded or failed. Every call this service actually makes to a vendor —
model calls through the Agent SDK, credential probes over httpx — is
asynchronous, so none of them could route through it, and the audit log at
`GET /api/audit/egress` stayed permanently empty while real calls left the
machine.

`record_egress` is that same invariant for an awaitable call. It does not
execute a transport itself: the caller supplies the call as a coroutine
function, because a model call returns a model's answer, not a byte count,
and forcing it through a transport shape would mean throwing that answer
away and fetching it back.

**What this does not do.** The synchronous chokepoint refuses a call whose
engagement has no pinned processing region (NFR-2.2). This records the
region on the row and lets the call proceed, so a call made with no pin
shows up in the audit as `region: null` rather than not showing up at all.
That is a deliberately smaller claim: these calls already went out unpinned
and unlogged, and making them visible is not the same as making them safe.
Enforcing the pin on this path is its own change, and the audit is what will
show whether it is needed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.egress.clock import EgressClock
from app.core.egress.models import EgressLogRow
from app.core.egress.region import EngagementRegionRegistry
from app.core.egress.sink import EgressLogSink


async def record_egress[T](
    call: Callable[[], Awaitable[T]],
    *,
    sink: EgressLogSink,
    clock: EgressClock,
    regions: EngagementRegionRegistry,
    engagement_id: str,
    processor_name: str,
    request_bytes: int = 0,
) -> T:
    """Run `call`, and write exactly one audit row for it either way.

    The row is written before the result is returned and before a failure is
    re-raised, so a caller cannot observe the outcome of a call that was not
    audited. A failure is recorded with the exception's text and then
    re-raised unchanged — auditing a call is not handling it.

    `request_bytes` defaults to 0 because a vendor SDK does not report what
    it put on the wire. Zero here means "not measured at this seam", which
    is why the row's value as an audit is `processor_name` and
    `timestamp_ms` — who was called, and when.
    """

    error: Exception | None = None
    try:
        return await call()
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised unchanged
        error = exc
        raise
    finally:
        sink.record(
            EgressLogRow(
                timestamp_ms=clock.now_ms(),
                engagement_id=engagement_id,
                processor_name=processor_name,
                region=regions.region_for(engagement_id),
                byte_count=request_bytes,
                success=error is None,
                error=str(error) if error is not None else None,
            )
        )


def audited(
    engine: Callable[..., Awaitable[Any]],
    *,
    sink: EgressLogSink,
    clock: EgressClock,
    regions: EngagementRegionRegistry,
    engagement_id: str,
    processor_name: str,
) -> Callable[..., Awaitable[Any]]:
    """Wrap one injected inference seam so every call it makes is audited.

    Wrapping the seam rather than asking each stage to log is what keeps the
    audit a property of the boundary instead of something eight stages have
    to remember, and it is why a stage added later is audited without anyone
    thinking about it.
    """

    async def call(*args: Any, **kwargs: Any) -> Any:
        return await record_egress(
            lambda: engine(*args, **kwargs),
            sink=sink,
            clock=clock,
            regions=regions,
            engagement_id=engagement_id,
            processor_name=processor_name,
        )

    return call
