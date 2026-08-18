from __future__ import annotations

import pytest

from app.modules.replay.log.errors import SuggestionLogError
from app.modules.replay.log.logger import SuggestionLogger
from app.modules.replay.log.models import SuggestionLogRow


class FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms


class SpySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.rows: list[SuggestionLogRow] = []
        self._fail = fail

    def record(self, row: SuggestionLogRow) -> None:
        if self._fail:
            raise SuggestionLogError("disk full")
        self.rows.append(row)


def test_logging_an_evaluation_persists_a_row_with_every_field():
    sink = SpySink()
    logger = SuggestionLogger(FixedClock(5_000), sink)

    logger.log_evaluation(
        trigger="vague_quantifier",
        candidate="cand-1",
        score=0.82,
        would_surface=True,
    )

    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.timestamp_ms == 5_000
    assert row.trigger == "vague_quantifier"
    assert row.candidate == "cand-1"
    assert row.score == 0.82
    assert row.would_surface is True


def test_exactly_one_row_is_persisted_per_evaluation():
    sink = SpySink()
    logger = SuggestionLogger(FixedClock(1_000), sink)

    for i in range(3):
        logger.log_evaluation(
            trigger="t",
            candidate=f"cand-{i}",
            score=0.1 * i,
            would_surface=(i == 2),
        )

    assert len(sink.rows) == 3
    assert [row.candidate for row in sink.rows] == ["cand-0", "cand-1", "cand-2"]


def test_a_losing_candidate_is_still_logged_with_would_surface_false():
    sink = SpySink()
    logger = SuggestionLogger(FixedClock(1_000), sink)

    logger.log_evaluation(
        trigger="t", candidate="cand-1", score=0.01, would_surface=False
    )

    assert len(sink.rows) == 1
    assert sink.rows[0].would_surface is False


def test_a_logging_failure_is_surfaced_rather_than_swallowed():
    logger = SuggestionLogger(FixedClock(1_000), SpySink(fail=True))

    with pytest.raises(SuggestionLogError, match="disk full"):
        logger.log_evaluation(
            trigger="t", candidate="cand-1", score=0.5, would_surface=True
        )
