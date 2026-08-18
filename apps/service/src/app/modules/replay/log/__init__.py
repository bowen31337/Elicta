"""Replay suggestion-log package: support layer for the `replay` module.

Exposes no router — this package is consumed by whichever part of the
`replay` module drives the full pipeline (trigger gate, bank retrieval,
ranking) against a replayed transcript. `SuggestionLogger.log_evaluation`
persists one `suggestion_log` row per candidate evaluation — timestamp,
trigger, candidate, score, and would_surface (architecture section 9, PRD
phase 0) — so the rating UI and the M1/M2 metrics have the full evaluation
population to work from, not just whichever candidate ultimately surfaced.
"""

from __future__ import annotations

from app.modules.replay.log.errors import SuggestionLogError
from app.modules.replay.log.logger import SuggestionLogger
from app.modules.replay.log.models import SuggestionLogRow
from app.modules.replay.log.sink import SuggestionLogSink

__all__ = [
    "SuggestionLogError",
    "SuggestionLogRow",
    "SuggestionLogSink",
    "SuggestionLogger",
]
