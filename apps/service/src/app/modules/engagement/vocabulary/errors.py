"""Errors surfaced by the engagement vocabulary API."""

from __future__ import annotations


class EngagementNotFoundError(Exception):
    """Raised when a vocabulary term is added to an engagement that does not exist."""
