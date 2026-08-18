"""The replay harness driver.

`ReplayHarness.run` seeds a fresh RNG from the request's `seed`, hands it to
the injected `ReplayWorkload`, and unconditionally persists a `replay_runs`
row (seed included) before returning the workload's output. Running the same
`ReplayRequest` (same `input_bytes`, same `seed`) through separate
`ReplayHarness` instances always produces byte-identical `output_bytes`,
since each run gets its own RNG seeded the same way rather than sharing
mutable state across runs.

The actual workload and the actual `replay_runs` persistence stay out of
this package (supplied via `ReplayWorkload` and `ReplayRunSink`). What lives
here is the invariant itself: a fixed input and seed always replay to the
same output, and every run's seed is recorded.
"""

from __future__ import annotations

import hashlib
import random

from app.modules.replay.driver.clock import RunClock
from app.modules.replay.driver.models import ReplayRequest, ReplayResult, ReplayRunRow
from app.modules.replay.driver.sink import ReplayRunSink
from app.modules.replay.driver.workload import ReplayWorkload


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReplayHarness:
    """Drives one workload run per `ReplayRequest` and audits it to `replay_runs`."""

    def __init__(
        self,
        clock: RunClock,
        workload: ReplayWorkload,
        sink: ReplayRunSink,
    ) -> None:
        self._clock = clock
        self._workload = workload
        self._sink = sink

    def run(self, request: ReplayRequest) -> ReplayResult:
        """Executes `request` and persists its `replay_runs` row before returning.

        The row's `seed` is what makes the run reproducible later; recording
        it is not optional, so a sink failure propagates as
        `ReplayRunLogError` rather than being swallowed.
        """

        rng = random.Random(request.seed)
        output_bytes = self._workload.execute(request.input_bytes, rng)
        output_digest = _digest(output_bytes)

        row = ReplayRunRow(
            run_id=request.run_id,
            seed=request.seed,
            input_digest=_digest(request.input_bytes),
            output_digest=output_digest,
            timestamp_ms=self._clock.now_ms(),
        )
        self._sink.record(row)

        return ReplayResult(output_bytes=output_bytes, output_digest=output_digest)
