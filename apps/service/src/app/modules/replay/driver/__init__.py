"""Replay harness driver: reproducible workload execution audited to `replay_runs`.

Exposes no router — this package is a support layer for the `replay` module
consumed by whichever part of it (e.g. an API layer) accepts replay requests
and wires a real `ReplayRunSink`.
"""

from __future__ import annotations

from app.modules.replay.driver.clock import ReplayClock, SystemClock
from app.modules.replay.driver.errors import ReplayRunLogError
from app.modules.replay.driver.harness import ReplayHarness
from app.modules.replay.driver.models import ReplayRequest, ReplayResult, ReplayRunRow
from app.modules.replay.driver.sink import ReplayRunSink
from app.modules.replay.driver.workload import ReplayWorkload

__all__ = [
    "ReplayClock",
    "SystemClock",
    "ReplayRunLogError",
    "ReplayHarness",
    "ReplayRequest",
    "ReplayResult",
    "ReplayRunRow",
    "ReplayRunSink",
    "ReplayWorkload",
]
