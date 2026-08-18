"""The `ReplayWorkload` that makes `ReplayHarness` run against the shared core.

`app.modules.replay.driver.ReplayHarness` already guarantees byte-identical
output for a fixed input and seed, but it does so around whatever
`ReplayWorkload` it's given — that workload is where the actual suggestion
computation happens. `CoreWorkload` is the one that plugs the shared Rust
core into that seam (PRD NFR-3.8), so running the harness in production
exercises the real cross-platform core rather than a Python re-implementation
of it.
"""

from __future__ import annotations

import random

from .engine import CoreEngine


class CoreWorkload:
    """Adapts a `CoreEngine` to the `ReplayWorkload` protocol.

    `ReplayHarness` hands this a `random.Random` seeded from the request's
    seed; a single 64-bit draw from it is forwarded to the core so the core
    itself — not this adapter — is what makes a fixed seed reproducible.
    """

    def __init__(self, engine: CoreEngine) -> None:
        self._engine = engine

    def execute(self, input_bytes: bytes, rng: random.Random) -> bytes:
        seed = rng.getrandbits(64)
        return self._engine.run(input_bytes, seed)
