from __future__ import annotations

import hashlib
import random

import pytest

from app.modules.replay.driver.errors import ReplayRunLogError
from app.modules.replay.driver.harness import ReplayHarness
from app.modules.replay.driver.models import ReplayRequest, ReplayRunRow


class FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms


class XorNoiseWorkload:
    """A workload whose output depends on both `input_bytes` and `rng`.

    Standing in for whatever domain computation a real replay run drives:
    what matters for these tests is that it draws its randomness solely
    from the RNG the harness seeds, so identical seeds reproduce identical
    output and different seeds diverge.
    """

    def execute(self, input_bytes: bytes, rng: random.Random) -> bytes:
        noise = bytes(rng.randrange(256) for _ in input_bytes)
        return bytes(byte ^ n for byte, n in zip(input_bytes, noise))


class SpySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.rows: list[ReplayRunRow] = []
        self._fail = fail

    def record(self, row: ReplayRunRow) -> None:
        if self._fail:
            raise ReplayRunLogError("disk full")
        self.rows.append(row)


def sample_request(**overrides: object) -> ReplayRequest:
    defaults = {
        "run_id": "run-1",
        "seed": 42,
        "input_bytes": b"the quick brown fox",
    }
    defaults.update(overrides)
    return ReplayRequest(**defaults)


def test_a_fixed_input_and_seed_produce_byte_identical_output_across_separate_runs():
    first_harness = ReplayHarness(FixedClock(1_000), XorNoiseWorkload(), SpySink())
    second_harness = ReplayHarness(FixedClock(2_000), XorNoiseWorkload(), SpySink())

    first_result = first_harness.run(sample_request())
    second_result = second_harness.run(sample_request())

    assert first_result.output_bytes == second_result.output_bytes
    assert first_result.output_digest == second_result.output_digest


def test_the_same_harness_instance_reproduces_identical_output_on_repeated_runs():
    harness = ReplayHarness(FixedClock(1_000), XorNoiseWorkload(), SpySink())

    first_result = harness.run(sample_request())
    second_result = harness.run(sample_request())

    assert first_result.output_bytes == second_result.output_bytes
    assert first_result.output_digest == second_result.output_digest


def test_a_different_seed_produces_different_output_for_the_same_input():
    harness = ReplayHarness(FixedClock(1_000), XorNoiseWorkload(), SpySink())

    first_result = harness.run(sample_request(seed=42))
    second_result = harness.run(sample_request(seed=43))

    assert first_result.output_bytes != second_result.output_bytes


def test_a_run_persists_its_seed_to_the_replay_runs_row():
    sink = SpySink()
    harness = ReplayHarness(FixedClock(5_000), XorNoiseWorkload(), sink)

    result = harness.run(sample_request(run_id="run-42", seed=7))

    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.run_id == "run-42"
    assert row.seed == 7
    assert row.timestamp_ms == 5_000
    assert row.input_digest == hashlib.sha256(b"the quick brown fox").hexdigest()
    assert row.output_digest == result.output_digest


def test_exactly_one_replay_runs_row_is_persisted_per_run():
    sink = SpySink()
    harness = ReplayHarness(FixedClock(1_000), XorNoiseWorkload(), sink)

    for seed in (1, 2, 3):
        harness.run(sample_request(seed=seed))

    assert len(sink.rows) == 3
    assert [row.seed for row in sink.rows] == [1, 2, 3]


def test_a_logging_failure_is_surfaced_rather_than_swallowed():
    harness = ReplayHarness(FixedClock(1_000), XorNoiseWorkload(), SpySink(fail=True))

    with pytest.raises(ReplayRunLogError, match="disk full"):
        harness.run(sample_request())
