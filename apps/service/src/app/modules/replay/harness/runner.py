"""Wires `CoreWorkload` into `ReplayHarness`: the actual entry point NFR-3.8
asks for — running the replay harness against the shared Rust core.

Kept as a thin function rather than a new harness class because
`ReplayHarness` already owns seeding, persistence, and digesting (feature
26); the only thing missing for it to run against the shared core was a
`ReplayWorkload` that does that, which is what `CoreWorkload` supplies.
"""

from __future__ import annotations

from app.modules.replay.driver.clock import RunClock
from app.modules.replay.driver.harness import ReplayHarness
from app.modules.replay.driver.models import ReplayRequest, ReplayResult
from app.modules.replay.driver.sink import ReplayRunSink

from .engine import CoreEngine
from .workload import CoreWorkload


def run_against_core(
    request: ReplayRequest,
    *,
    engine: CoreEngine,
    clock: RunClock,
    sink: ReplayRunSink,
) -> ReplayResult:
    """Runs `request` through the shared Rust core and returns its result.

    `result.output_bytes` is the core's raw suggestion log (NDJSON) for
    this run; parse it with `suggestion_log.parse_suggestion_log` before
    comparing it across platforms with `comparison.assert_identical_suggestion_logs`.
    """

    harness = ReplayHarness(clock, CoreWorkload(engine), sink)
    return harness.run(request)
