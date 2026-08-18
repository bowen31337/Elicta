"""Supplies the audit row's timestamp.

Left as a `Protocol` purely so tests can hold time fixed; production callers
can use `SystemClock`.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class EgressClock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    """Wall-clock `EgressClock`."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)
