"""Runs the replay harness against the shared Rust core (PRD NFR-3.8).

Exposes no router — this package is support for the `replay` module,
consumed by whichever part of it drives an actual replay run. It supplies
the piece `app.modules.replay.driver.ReplayHarness` was deliberately left
without: a `ReplayWorkload` (`CoreWorkload`) that executes the real,
cross-platform shared core (via `CoreEngine`/`SubprocessCoreEngine`) instead
of a Python stand-in, so identical suggestion-log output across platforms is
demonstrated by actually running the same core rather than assumed.
"""

from __future__ import annotations

from .comparison import assert_identical_suggestion_logs
from .engine import CoreEngine
from .errors import CoreProcessError, SuggestionLogError, SuggestionLogMismatchError
from .runner import run_against_core
from .subprocess_engine import SubprocessCoreEngine
from .suggestion_log import SuggestionLogEntry, parse_suggestion_log
from .workload import CoreWorkload

__all__ = [
    "CoreEngine",
    "CoreProcessError",
    "CoreWorkload",
    "SubprocessCoreEngine",
    "SuggestionLogEntry",
    "SuggestionLogError",
    "SuggestionLogMismatchError",
    "assert_identical_suggestion_logs",
    "parse_suggestion_log",
    "run_against_core",
]
