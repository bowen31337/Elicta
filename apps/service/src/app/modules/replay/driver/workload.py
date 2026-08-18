"""The computation the replay harness drives.

Left as a `Protocol` so the actual workload being replayed (whatever
domain logic a run reproduces) stays out of this package — the harness only
needs to know how to hand it a seeded RNG.
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable


@runtime_checkable
class ReplayWorkload(Protocol):
    """Executes one replay run.

    ``rng`` is seeded by the harness from the request's ``seed`` before this
    is called. Any randomness the workload needs must come from ``rng``
    rather than a fresh, unseeded source — that is the only way the
    harness's "byte-identical output for a fixed input and seed" guarantee
    holds.
    """

    def execute(self, input_bytes: bytes, rng: random.Random) -> bytes: ...
