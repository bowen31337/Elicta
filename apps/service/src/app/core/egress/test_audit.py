"""The async egress audit writes exactly one row per call, either way."""

from __future__ import annotations

import asyncio

import pytest

from app.core.egress.audit import audited, record_egress
from app.core.egress.models import EgressLogRow
from app.core.egress.region import EngagementRegionRegistry


class _Sink:
    def __init__(self) -> None:
        self.rows: list[EgressLogRow] = []

    def record(self, row: EgressLogRow) -> None:
        self.rows.append(row)


class _FrozenClock:
    def now_ms(self) -> int:
        return 1_700_000_000_000


def _record(call, *, regions=None, sink=None):
    return asyncio.run(
        record_egress(
            call,
            sink=sink if sink is not None else _Sink(),
            clock=_FrozenClock(),
            regions=regions or EngagementRegionRegistry({"eng-1": "eu-west-1"}),
            engagement_id="eng-1",
            processor_name="claude-opus-5",
        )
    )


def test_a_successful_call_returns_its_result_and_writes_one_row():
    sink = _Sink()

    async def call() -> str:
        return "the model's answer"

    result = _record(call, sink=sink)

    assert result == "the model's answer"
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.processor_name == "claude-opus-5"
    assert row.engagement_id == "eng-1"
    assert row.region == "eu-west-1"
    assert row.timestamp_ms == 1_700_000_000_000
    assert row.success is True
    assert row.error is None


def test_a_failing_call_is_recorded_and_re_raised_unchanged():
    sink = _Sink()

    async def call() -> str:
        raise RuntimeError("the vendor returned 500")

    with pytest.raises(RuntimeError, match="the vendor returned 500"):
        _record(call, sink=sink)

    assert len(sink.rows) == 1
    assert sink.rows[0].success is False
    assert "the vendor returned 500" in sink.rows[0].error


def test_a_call_for_an_unpinned_engagement_is_recorded_with_no_region():
    """The pin is what NFR-2.2 governs; the audit's job is to show it is missing."""

    sink = _Sink()

    async def call() -> str:
        return "sent anyway"

    _record(call, regions=EngagementRegionRegistry(), sink=sink)

    assert sink.rows[0].region is None


def test_audited_wraps_a_seam_and_passes_its_arguments_through():
    sink = _Sink()
    seen: list[tuple] = []

    async def engine(session_id: str, utterances: list[str]) -> int:
        seen.append((session_id, utterances))
        return len(utterances)

    wrapped = audited(
        engine,
        sink=sink,
        clock=_FrozenClock(),
        regions=EngagementRegionRegistry({"eng-1": "eu-west-1"}),
        engagement_id="eng-1",
        processor_name="claude-opus-5",
    )

    assert asyncio.run(wrapped("session-1", ["a", "b"])) == 2
    assert seen == [("session-1", ["a", "b"])]
    assert len(sink.rows) == 1
