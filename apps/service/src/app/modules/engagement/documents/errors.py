"""Errors raised by the engagement documents API layer."""

from __future__ import annotations


class EngagementNotFoundError(Exception):
    """Raised by a listing callback when `engagement_id` has no known engagement."""
