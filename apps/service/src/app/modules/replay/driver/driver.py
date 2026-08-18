"""Deterministic replay driver (architecture section 9, PRD phase 0).

Replays a recorded meeting transcript through a pipeline sink, emitting each
utterance at the wall-clock offset it originally occurred at, so the full
pipeline sees the same pacing it would have during the live meeting.
"""

from __future__ import annotations

from .clock import ReplayClock, WallClock
from .sink import PipelineSink
from .transcript import RecordedTranscript


class ReplayDriver:
    def __init__(self, sink: PipelineSink, clock: ReplayClock | None = None) -> None:
        self._sink = sink
        self._clock = clock if clock is not None else WallClock()

    async def run(self, transcript: RecordedTranscript) -> None:
        self._clock.start()
        for utterance in transcript.ordered_by_offset():
            wait_ms = utterance.start_ms - self._clock.elapsed_ms()
            if wait_ms > 0:
                await self._clock.sleep(wait_ms / 1000)
            await self._sink.handle_utterance(utterance)
