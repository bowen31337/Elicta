"""Replay driver package: support layer for the `replay` module.

Exposes no router — this package is consumed by whichever part of the
`replay` module (e.g. an API layer) accepts replay requests. It holds two
unrelated pieces of functionality that both happen to live here:

- `ReplayDriver`: replays a recorded meeting transcript through a
  `PipelineSink`, emitting each utterance at its original wall-clock offset
  (architecture section 9, PRD phase 0).
- `ReplayHarness`: runs a `ReplayWorkload` from a fixed seed and audits the
  run to `replay_runs`, guaranteeing byte-identical output for a fixed input
  and seed (feature 26).
"""

from __future__ import annotations

from app.modules.replay.driver.clock import (
    ReplayClock,
    RunClock,
    SystemClock,
    WallClock,
)
from app.modules.replay.driver.driver import ReplayDriver
from app.modules.replay.driver.errors import ReplayRunLogError
from app.modules.replay.driver.harness import ReplayHarness
from app.modules.replay.driver.models import ReplayRequest, ReplayResult, ReplayRunRow
from app.modules.replay.driver.sink import PipelineSink, ReplayRunSink
from app.modules.replay.driver.transcript import RecordedTranscript, RecordedUtterance
from app.modules.replay.driver.workload import ReplayWorkload

__all__ = [
    "PipelineSink",
    "RecordedTranscript",
    "RecordedUtterance",
    "ReplayClock",
    "ReplayDriver",
    "ReplayHarness",
    "ReplayRequest",
    "ReplayResult",
    "ReplayRunLogError",
    "ReplayRunRow",
    "ReplayRunSink",
    "ReplayWorkload",
    "RunClock",
    "SystemClock",
    "WallClock",
]
