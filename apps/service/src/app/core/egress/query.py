"""Reads rows back out of the `egress_log` table for audit purposes.

Left as a `Protocol`, mirroring `EgressLogSink` on the write side, so the
storage binding (the real `egress_log` table) stays out of this package —
whoever wires the audit endpoint to a real database supplies the
implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.egress.models import EgressLogRow


@runtime_checkable
class EgressLogQuery(Protocol):
    async def query(
        self, engagement_id: str, start_ms: int, end_ms: int
    ) -> list[EgressLogRow]: ...
