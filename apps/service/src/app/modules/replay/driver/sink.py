"""Hand-off points out of the replay driver package.

`PipelineSink` is the hand-off between the transcript-pacing `ReplayDriver`
and the full pipeline (trigger gate, bank retrieval, ranking); that pipeline
is bound to this from outside the driver module, so the driver stays
testable without importing any of it.

`ReplayRunSink` is unrelated: it persists one `ReplayRunRow` to the
`replay_runs` table for `ReplayHarness` (feature 26, byte-identical output
for a fixed seed). Left as a `Protocol` so the storage binding (the real
`replay_runs` table) stays out of this package — whoever wires the harness
to a real database supplies the implementation, raising `ReplayRunLogError`
on failure.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.replay.driver.models import ReplayRunRow

from .transcript import RecordedUtterance


@runtime_checkable
class PipelineSink(Protocol):
    async def handle_utterance(self, utterance: RecordedUtterance) -> None: ...


@runtime_checkable
class ReplayRunSink(Protocol):
    def record(self, row: ReplayRunRow) -> None: ...
