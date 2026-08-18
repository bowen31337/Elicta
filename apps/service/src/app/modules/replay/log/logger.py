"""Writes the replay harness's `suggestion_log` audit trail.

`SuggestionLogger.log_evaluation` is the hand-off between the full pipeline
(trigger gate, bank retrieval, ranking) replayed against a recorded
transcript and the `suggestion_log` table (architecture section 9). It is
called once per candidate evaluation — every candidate the ranking function
scores against a fired trigger, whether or not it ends up being the one
that would surface — so the rating UI and the M1 (precision@surfaced) / M2
(embarrassment count) metrics have the full evaluation population to work
from rather than only the winning candidate.

This is distinct from `driver.harness.ReplayHarness`'s `replay_runs` row,
which audits one row per *run* (the seed, for byte-identical reproduction).
This logs one row per *evaluation within* a run.
"""

from __future__ import annotations

from app.modules.replay.driver.clock import RunClock
from app.modules.replay.log.models import SuggestionLogRow
from app.modules.replay.log.sink import SuggestionLogSink


class SuggestionLogger:
    def __init__(self, clock: RunClock, sink: SuggestionLogSink) -> None:
        self._clock = clock
        self._sink = sink

    def log_evaluation(
        self,
        *,
        trigger: str,
        candidate: str,
        score: float,
        would_surface: bool,
    ) -> SuggestionLogRow:
        """Builds and persists one `suggestion_log` row for one evaluation.

        A sink failure (`SuggestionLogError`) propagates rather than being
        caught here — the sink implementation is the one place storage
        errors are turned into that error, per its own `Protocol` contract.
        """

        row = SuggestionLogRow(
            timestamp_ms=self._clock.now_ms(),
            trigger=trigger,
            candidate=candidate,
            score=score,
            would_surface=would_surface,
        )
        self._sink.record(row)
        return row
