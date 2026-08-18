"""Persists one `ReplayRunRow` to the `replay_runs` table.

Left as a `Protocol` so the storage binding (the real `replay_runs` table)
stays out of this package — whoever wires the harness to a real database
supplies the implementation, raising `ReplayRunLogError` on failure.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.replay.driver.models import ReplayRunRow


@runtime_checkable
class ReplayRunSink(Protocol):
    def record(self, row: ReplayRunRow) -> None: ...
