"""Errors raised by the compiler API layer."""

from __future__ import annotations


class CandidateNotFoundError(Exception):
    """Raised by a delete callback when `candidate_id` has no known bank candidate."""
