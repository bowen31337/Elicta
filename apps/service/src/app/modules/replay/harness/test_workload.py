from __future__ import annotations

import random

from app.modules.replay.driver.workload import ReplayWorkload

from .workload import CoreWorkload


class SpyEngine:
    def __init__(self, output: bytes = b'{"span_id": "s1"}\n') -> None:
        self._output = output
        self.calls: list[tuple[bytes, int]] = []

    def run(self, input_bytes: bytes, seed: int) -> bytes:
        self.calls.append((input_bytes, seed))
        return self._output


def test_core_workload_satisfies_the_replay_workload_protocol():
    assert isinstance(CoreWorkload(SpyEngine()), ReplayWorkload)


def test_execute_forwards_input_bytes_and_a_seed_derived_from_rng():
    engine = SpyEngine()
    workload = CoreWorkload(engine)

    workload.execute(b"transcript bytes", random.Random(42))

    assert len(engine.calls) == 1
    forwarded_input, forwarded_seed = engine.calls[0]
    assert forwarded_input == b"transcript bytes"
    assert isinstance(forwarded_seed, int)


def test_the_same_rng_seed_produces_the_same_forwarded_core_seed():
    first_engine = SpyEngine()
    second_engine = SpyEngine()

    CoreWorkload(first_engine).execute(b"input", random.Random(7))
    CoreWorkload(second_engine).execute(b"input", random.Random(7))

    assert first_engine.calls[0][1] == second_engine.calls[0][1]


def test_a_different_rng_seed_produces_a_different_forwarded_core_seed():
    first_engine = SpyEngine()
    second_engine = SpyEngine()

    CoreWorkload(first_engine).execute(b"input", random.Random(7))
    CoreWorkload(second_engine).execute(b"input", random.Random(8))

    assert first_engine.calls[0][1] != second_engine.calls[0][1]


def test_execute_returns_the_engines_output_unchanged():
    engine = SpyEngine(output=b'{"span_id": "abc"}\n')

    result = CoreWorkload(engine).execute(b"input", random.Random(1))

    assert result == b'{"span_id": "abc"}\n'
