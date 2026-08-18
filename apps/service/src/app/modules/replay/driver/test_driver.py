import time

import pytest

from .clock import WallClock
from .driver import ReplayDriver
from .transcript import RecordedTranscript, RecordedUtterance


class FakeClock:
    """Advances only when `sleep` is awaited or the test calls `advance`,
    so tests assert on requested wait durations instead of burning real time."""

    def __init__(self) -> None:
        self._elapsed_ms = 0
        self._started = False
        self.sleep_calls: list[float] = []

    def start(self) -> None:
        self._started = True
        self._elapsed_ms = 0

    def elapsed_ms(self) -> int:
        assert self._started, "start() must be called before elapsed_ms()"
        return self._elapsed_ms

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self._elapsed_ms += round(seconds * 1000)

    def advance(self, ms: int) -> None:
        self._elapsed_ms += ms


class RecordingSink:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.received: list[RecordedUtterance] = []
        self.emitted_at_ms: list[int] = []
        self._clock = clock

    async def handle_utterance(self, utterance: RecordedUtterance) -> None:
        self.received.append(utterance)
        if self._clock is not None:
            self.emitted_at_ms.append(self._clock.elapsed_ms())


def _utterance(utterance_id: str, start_ms: int) -> RecordedUtterance:
    return RecordedUtterance(
        utterance_id=utterance_id,
        speaker_tag="speaker-1",
        text="hello",
        start_ms=start_ms,
    )


@pytest.mark.asyncio
async def test_emits_utterances_in_offset_order() -> None:
    clock = FakeClock()
    sink = RecordingSink(clock)
    transcript = RecordedTranscript(
        utterances=[
            _utterance("u3", 3000),
            _utterance("u1", 0),
            _utterance("u2", 1500),
        ]
    )

    await ReplayDriver(sink=sink, clock=clock).run(transcript)

    assert [u.utterance_id for u in sink.received] == ["u1", "u2", "u3"]


@pytest.mark.asyncio
async def test_waits_the_delta_between_offsets() -> None:
    clock = FakeClock()
    sink = RecordingSink(clock)
    transcript = RecordedTranscript(
        utterances=[
            _utterance("u1", 0),
            _utterance("u2", 1000),
            _utterance("u3", 2500),
        ]
    )

    await ReplayDriver(sink=sink, clock=clock).run(transcript)

    # No wait before the first utterance (offset 0), then exactly the gap to
    # each subsequent one.
    assert clock.sleep_calls == [1.0, 1.5]
    assert sink.emitted_at_ms == [0, 1000, 2500]


@pytest.mark.asyncio
async def test_does_not_wait_for_utterances_sharing_an_offset() -> None:
    clock = FakeClock()
    sink = RecordingSink(clock)
    transcript = RecordedTranscript(
        utterances=[
            _utterance("first-at-500", 500),
            _utterance("second-at-500", 500),
        ]
    )

    await ReplayDriver(sink=sink, clock=clock).run(transcript)

    assert clock.sleep_calls == [0.5]
    assert [u.utterance_id for u in sink.received] == ["first-at-500", "second-at-500"]


@pytest.mark.asyncio
async def test_never_sleeps_a_negative_duration_when_running_behind() -> None:
    """If handling one utterance took longer than the gap to the next, replay
    must catch up immediately rather than ask the clock to sleep negative
    time."""
    clock = FakeClock()
    sink = RecordingSink(clock)
    transcript = RecordedTranscript(
        utterances=[
            _utterance("u1", 0),
            _utterance("u2", 100),
        ]
    )

    async def handle_utterance(utterance: RecordedUtterance) -> None:
        sink.received.append(utterance)
        if utterance.utterance_id == "u1":
            clock.advance(5_000)  # downstream processing overran the gap

    sink.handle_utterance = handle_utterance  # type: ignore[method-assign]

    await ReplayDriver(sink=sink, clock=clock).run(transcript)

    assert clock.sleep_calls == []
    assert [u.utterance_id for u in sink.received] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_empty_transcript_emits_nothing() -> None:
    clock = FakeClock()
    sink = RecordingSink(clock)

    await ReplayDriver(sink=sink, clock=clock).run(RecordedTranscript(utterances=[]))

    assert sink.received == []
    assert clock.sleep_calls == []


@pytest.mark.asyncio
async def test_wall_clock_actually_paces_real_time() -> None:
    """End-to-end with the production clock: real elapsed time tracks the
    recorded offsets, not just the fake-clock bookkeeping above."""
    sink = RecordingSink()
    transcript = RecordedTranscript(
        utterances=[
            _utterance("u1", 0),
            _utterance("u2", 40),
            _utterance("u3", 90),
        ]
    )

    started = time.monotonic()
    await ReplayDriver(sink=sink, clock=WallClock()).run(transcript)
    elapsed_ms = (time.monotonic() - started) * 1000

    assert [u.utterance_id for u in sink.received] == ["u1", "u2", "u3"]
    assert elapsed_ms >= 90
    # Generous scheduling slack, still far from wall-clock speed being wrong.
    assert elapsed_ms < 90 + 250
