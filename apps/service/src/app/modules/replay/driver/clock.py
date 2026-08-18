"""Time sources used by the replay driver package.

`ReplayClock` is what the transcript-pacing `ReplayDriver` waits on so replay
proceeds at the recording's original pace; kept as a `Protocol` so tests can
drive it with a fake clock instead of waiting on real wall-clock delays.
`WallClock` is its production implementation.

`RunClock` is unrelated: it only supplies the timestamp on a `replay_runs`
audit row written by `ReplayHarness` (feature 26, byte-identical output for a
fixed seed). Left as a `Protocol` purely so tests can hold that time fixed;
production callers use `SystemClock`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class ReplayClock(Protocol):
    def start(self) -> None:
        """Mark the origin that `elapsed_ms` is measured from."""
        ...

    def elapsed_ms(self) -> int:
        """Milliseconds since `start()` was called."""
        ...

    async def sleep(self, seconds: float) -> None: ...


class WallClock:
    """Real wall-clock time, so replay proceeds at the recording's original pace."""

    def __init__(self) -> None:
        self._start: float | None = None

    def start(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        if self._start is None:
            raise RuntimeError("WallClock.start() must be called before elapsed_ms()")
        return int((time.monotonic() - self._start) * 1000)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@runtime_checkable
class RunClock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    """Wall-clock `RunClock`."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)
