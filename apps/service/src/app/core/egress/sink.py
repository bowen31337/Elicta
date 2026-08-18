"""Persists one `EgressLogRow` to the `egress_log` table.

Left as a `Protocol` so the storage binding (the real `egress_log` table)
stays out of this package — whoever wires the chokepoint to a real database
supplies the implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.egress.models import EgressLogRow


@runtime_checkable
class EgressLogSink(Protocol):
    def record(self, row: EgressLogRow) -> None: ...
