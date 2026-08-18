from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.egress.models import EgressLogRow
from app.core.egress.router import build_egress_audit_router


class StubEgressLogQuery:
    def __init__(self, rows: list[EgressLogRow]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, int, int]] = []

    async def query(
        self, engagement_id: str, start_ms: int, end_ms: int
    ) -> list[EgressLogRow]:
        self.calls.append((engagement_id, start_ms, end_ms))
        return [
            row
            for row in self._rows
            if row.engagement_id == engagement_id
            and start_ms <= row.timestamp_ms <= end_ms
        ]


def make_client(rows: list[EgressLogRow]) -> tuple[TestClient, StubEgressLogQuery]:
    query = StubEgressLogQuery(rows)
    app = FastAPI()
    app.include_router(build_egress_audit_router(query))
    return TestClient(app), query


def sample_row(**overrides: object) -> EgressLogRow:
    defaults: dict[str, object] = {
        "timestamp_ms": 1_000,
        "engagement_id": "engagement-1",
        "processor_name": "transcription-vendor",
        "region": "eu-west-1",
        "byte_count": 100,
        "success": True,
        "error": None,
    }
    defaults.update(overrides)
    return EgressLogRow(**defaults)


def test_returns_200_with_rows_for_the_engagement_within_the_date_range():
    client, _ = make_client(
        [
            sample_row(timestamp_ms=1_000, engagement_id="engagement-1"),
            sample_row(timestamp_ms=5_000, engagement_id="engagement-1"),
        ]
    )

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "engagement-1", "start_ms": 0, "end_ms": 10_000},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {row["timestamp_ms"] for row in body} == {1_000, 5_000}


def test_rows_outside_the_date_range_are_excluded():
    client, _ = make_client(
        [
            sample_row(timestamp_ms=1_000, engagement_id="engagement-1"),
            sample_row(timestamp_ms=20_000, engagement_id="engagement-1"),
        ]
    )

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "engagement-1", "start_ms": 0, "end_ms": 10_000},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["timestamp_ms"] == 1_000


def test_rows_for_a_different_engagement_are_excluded():
    client, _ = make_client(
        [
            sample_row(engagement_id="engagement-1"),
            sample_row(engagement_id="engagement-2"),
        ]
    )

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "engagement-1", "start_ms": 0, "end_ms": 10_000},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["engagement_id"] == "engagement-1"


def test_engagement_id_is_forwarded_to_the_query_callback():
    client, query = make_client([])

    client.get(
        "/api/audit/egress",
        params={"engagement_id": "engagement-1", "start_ms": 0, "end_ms": 10_000},
    )

    assert query.calls == [("engagement-1", 0, 10_000)]


def test_an_end_before_start_is_rejected():
    client, _ = make_client([])

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "engagement-1", "start_ms": 10_000, "end_ms": 0},
    )

    assert response.status_code == 422


def test_missing_engagement_id_is_rejected():
    client, _ = make_client([])

    response = client.get(
        "/api/audit/egress", params={"start_ms": 0, "end_ms": 10_000}
    )

    assert response.status_code == 422
