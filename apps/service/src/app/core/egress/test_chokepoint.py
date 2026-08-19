import pytest

from app.core.egress.chokepoint import EgressChokepoint
from app.core.egress.errors import (
    EgressLogError,
    EgressRegionError,
    EgressTransportError,
)
from app.core.egress.models import EgressLogRow, ProcessorRequest, ProcessorSuccess
from app.core.egress.region import EngagementRegionRegistry


class FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms


class StubTransport:
    def __init__(self, outcome: ProcessorSuccess | EgressTransportError) -> None:
        self._outcome = outcome

    def execute(self, request: ProcessorRequest) -> ProcessorSuccess:
        if isinstance(self._outcome, EgressTransportError):
            raise self._outcome
        return self._outcome


class SpySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.rows: list[EgressLogRow] = []
        self._fail = fail

    def record(self, row: EgressLogRow) -> None:
        if self._fail:
            raise EgressLogError("disk full")
        self.rows.append(row)


def sample_request(**overrides: object) -> ProcessorRequest:
    defaults = {
        "processor_name": "transcription-vendor",
        "engagement_id": "engagement-1",
        "destination": "https://processor.example/run",
        "body_bytes": 1024,
    }
    defaults.update(overrides)
    return ProcessorRequest(**defaults)


def pinned_registry(region: str = "eu-west-1", engagement_id: str = "engagement-1") -> EngagementRegionRegistry:
    return EngagementRegionRegistry({engagement_id: region})


def test_a_successful_call_still_persists_an_egress_log_row():
    sink = SpySink()
    chokepoint = EgressChokepoint(
        FixedClock(1_000),
        StubTransport(ProcessorSuccess(response_bytes=64)),
        sink,
        pinned_registry(),
    )

    result = chokepoint.send(sample_request())

    assert result.response_bytes == 64
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.timestamp_ms == 1_000
    assert row.processor_name == "transcription-vendor"
    assert row.byte_count == 1024 + 64
    assert row.success is True
    assert row.error is None


def test_the_engagements_pinned_region_persists_on_the_egress_log_row():
    sink = SpySink()
    chokepoint = EgressChokepoint(
        FixedClock(1_000),
        StubTransport(ProcessorSuccess(response_bytes=64)),
        sink,
        pinned_registry(region="eu-west-1"),
    )

    chokepoint.send(sample_request())

    assert sink.rows[0].region == "eu-west-1"


def test_a_call_for_an_engagement_with_no_pinned_region_never_reaches_the_transport():
    sink = SpySink()
    chokepoint = EgressChokepoint(
        FixedClock(1_000),
        StubTransport(ProcessorSuccess(response_bytes=64)),
        sink,
        EngagementRegionRegistry(),
    )

    with pytest.raises(EgressRegionError, match="engagement-1"):
        chokepoint.send(sample_request())

    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.region is None
    assert row.success is False
    assert row.byte_count == 0


def test_a_failed_call_still_persists_an_egress_log_row_and_surfaces_the_transport_error():
    sink = SpySink()
    chokepoint = EgressChokepoint(
        FixedClock(2_000),
        StubTransport(EgressTransportError("connection refused")),
        sink,
        pinned_registry(),
    )

    with pytest.raises(EgressTransportError, match="connection refused"):
        chokepoint.send(sample_request())

    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.success is False
    assert row.error == "connection refused"
    assert row.byte_count == 1024
    assert row.region == "eu-west-1"


def test_a_logging_failure_is_surfaced_even_when_the_call_itself_succeeded():
    sink = SpySink(fail=True)
    chokepoint = EgressChokepoint(
        FixedClock(3_000),
        StubTransport(ProcessorSuccess(response_bytes=64)),
        sink,
        pinned_registry(),
    )

    with pytest.raises(EgressLogError, match="disk full"):
        chokepoint.send(sample_request())


def test_every_call_through_the_chokepoint_persists_exactly_one_row_regardless_of_outcome():
    success_sink = SpySink()
    success_chokepoint = EgressChokepoint(
        FixedClock(4_000),
        StubTransport(ProcessorSuccess(response_bytes=0)),
        success_sink,
        pinned_registry(),
    )
    failure_sink = SpySink()
    failure_chokepoint = EgressChokepoint(
        FixedClock(4_001),
        StubTransport(EgressTransportError("timeout")),
        failure_sink,
        pinned_registry(),
    )

    for _ in range(3):
        success_chokepoint.send(sample_request())
    for _ in range(2):
        with pytest.raises(EgressTransportError):
            failure_chokepoint.send(sample_request(processor_name="diarization-vendor"))

    assert len(success_sink.rows) == 3
    assert len(failure_sink.rows) == 2
    assert all(row.processor_name == "diarization-vendor" for row in failure_sink.rows)
