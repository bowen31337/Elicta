"""Domain types for the replay harness driver."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReplayRequest(BaseModel):
    """One request to run a workload through the replay harness.

    ``seed`` is what makes the run reproducible: the harness seeds a fresh
    RNG from it before invoking the workload, so the same ``seed`` and
    ``input_bytes`` always produce the same ``output_bytes``.
    """

    run_id: str = Field(min_length=1)
    seed: int
    input_bytes: bytes


class ReplayResult(BaseModel):
    """The workload's output for one replay run."""

    output_bytes: bytes
    output_digest: str


class ReplayRunRow(BaseModel):
    """One row as written to the `replay_runs` table.

    Persisting ``seed`` alongside the input/output digests is what lets a
    later run be replayed and checked for byte-identical output — a run
    whose seed was never recorded can't be reproduced.
    """

    run_id: str
    seed: int
    input_digest: str
    output_digest: str
    timestamp_ms: int
