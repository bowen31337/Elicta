"""Errors raised by the shared-core replay harness (PRD NFR-3.8)."""

from __future__ import annotations


class CoreProcessError(Exception):
    """Raised when the shared Rust core process can't be run or fails.

    Covers a missing/unexecutable binary, a launch failure, and a nonzero
    exit code. Left unswallowed: a harness that silently fell back to
    "no suggestions" on a core crash would hide exactly the divergence
    NFR-3.8 exists to catch.
    """


class SuggestionLogError(Exception):
    """Raised when a suggestion log can't be parsed as well-formed NDJSON.

    A log the harness can't parse can't be compared across platforms
    either, so this propagates rather than being treated as an empty log.
    """


class SuggestionLogMismatchError(Exception):
    """Raised when two platforms' suggestion logs for the same run diverge.

    This is the failure NFR-3.8 is written against: cross-platform
    identical behaviour must be demonstrated, not assumed, so a divergence
    found while demonstrating it is a hard error, not a warning.
    """
