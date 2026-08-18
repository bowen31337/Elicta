from __future__ import annotations

import random

from app.modules.replay.driver.models import ReplayRequest, ReplayRunRow

from .runner import run_against_core


class FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms


class SpySink:
    def __init__(self) -> None:
        self.rows: list[ReplayRunRow] = []

    def record(self, row: ReplayRunRow) -> None:
        self.rows.append(row)


class FakeCoreEngine:
    """Stands in for the shared Rust core: deterministic given (input, seed),
    exactly like the real core is required to be."""

    def run(self, input_bytes: bytes, seed: int) -> bytes:
        return b'{"span_id": "%s", "candidate_id": "%d"}\n' % (input_bytes, seed)


def _request(**overrides: object) -> ReplayRequest:
    defaults = {"run_id": "run-1", "seed": 42, "input_bytes": b"transcript"}
    defaults.update(overrides)
    return ReplayRequest(**defaults)


def test_running_against_the_core_returns_its_suggestion_log_as_output_bytes():
    result = run_against_core(
        _request(),
        engine=FakeCoreEngine(),
        clock=FixedClock(1_000),
        sink=SpySink(),
    )

    expected_seed = random.Random(42).getrandbits(64)
    assert result.output_bytes == b'{"span_id": "transcript", "candidate_id": "%d"}\n' % (
        expected_seed,
    )


def test_running_against_the_core_still_persists_a_replay_runs_row():
    sink = SpySink()

    run_against_core(
        _request(run_id="run-7", seed=99),
        engine=FakeCoreEngine(),
        clock=FixedClock(5_000),
        sink=sink,
    )

    assert len(sink.rows) == 1
    assert sink.rows[0].run_id == "run-7"
    assert sink.rows[0].seed == 99


def test_a_fixed_input_and_seed_reproduce_byte_identical_output_via_the_core():
    first = run_against_core(
        _request(),
        engine=FakeCoreEngine(),
        clock=FixedClock(1_000),
        sink=SpySink(),
    )
    second = run_against_core(
        _request(),
        engine=FakeCoreEngine(),
        clock=FixedClock(2_000),
        sink=SpySink(),
    )

    assert first.output_bytes == second.output_bytes
    assert first.output_digest == second.output_digest
