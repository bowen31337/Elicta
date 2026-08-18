"""Errors raised by the replay suggestion-log package."""

from __future__ import annotations


class SuggestionLogError(Exception):
    """Raised when a `suggestion_log` row fails to persist.

    An evaluation that silently fails to log is invisible to the rating UI
    and to the M1/M2 metrics (architecture section 9), so this propagates
    rather than being swallowed.
    """
