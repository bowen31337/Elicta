"""Errors raised by the replay API layer."""

from __future__ import annotations


class ReplayRunNotFoundError(Exception):
    """Raised by a status lookup callback when `run_id` has no known run."""
