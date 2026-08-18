"""The seam between the replay harness and the shared Rust core (PRD NFR-3.8).

NFR-3.8 asks for cross-platform identical behaviour to be *demonstrated*
rather than *assumed*. That demonstration only means something if the code
the harness runs on every platform is the same shared Rust core rather than
a per-platform Python stand-in — so `CoreEngine` is left as a `Protocol`
purely to keep any such stand-in out of this package. Production code is
wired to `SubprocessCoreEngine`, which runs the actual compiled core binary
and contains no suggestion logic of its own for a platform to diverge on.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CoreEngine(Protocol):
    """Runs one input through the shared Rust core and returns its raw
    suggestion log output (NDJSON bytes, see `suggestion_log.py`).

    `seed` is forwarded to the core so that, for a fixed `input_bytes` and
    `seed`, every platform's core binary produces the same suggestion log —
    the property NFR-3.8 requires the harness to demonstrate.
    """

    def run(self, input_bytes: bytes, seed: int) -> bytes: ...
