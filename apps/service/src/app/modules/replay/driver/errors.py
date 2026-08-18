"""Errors raised by the replay harness driver."""

from __future__ import annotations


class ReplayRunLogError(Exception):
    """Raised when a `replay_runs` row fails to persist.

    A replay run that can't be audited defeats the point of the harness
    (its seed would be lost, so the run could never be reproduced), so this
    propagates rather than being swallowed.
    """
