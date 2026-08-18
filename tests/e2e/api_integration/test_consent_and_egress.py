"""Happy-path 200/201 and documented-4xx coverage for consent + egress-audit."""

from __future__ import annotations

from app.core.consent.models import ConsentModel
from fastapi.testclient import TestClient

from conftest import Backend


def test_get_consent_gate_returns_200(client: TestClient, backend: Backend) -> None:
    backend.consent_models["e1"] = ConsentModel.PER_MEETING

    response = client.get("/api/meetings/m1/consent-gate", params={"engagement_id": "e1"})

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_confirmation"


def test_get_consent_gate_missing_required_query_param_returns_422(client: TestClient) -> None:
    response = client.get("/api/meetings/m1/consent-gate")

    assert response.status_code == 422


def test_confirm_consent_returns_201(client: TestClient, backend: Backend) -> None:
    response = client.post(
        "/api/meetings/m1/consent-confirmation", json={"confirmed_by": "operator-1"}
    )

    assert response.status_code == 201
    assert response.json()["meeting_id"] == "m1"
    assert len(backend.consent_records) == 1


def test_confirm_consent_blank_operator_returns_422(client: TestClient) -> None:
    response = client.post("/api/meetings/m1/consent-confirmation", json={"confirmed_by": ""})

    assert response.status_code == 422


def test_get_egress_audit_log_returns_200(client: TestClient, backend: Backend) -> None:
    from app.core.egress.models import EgressLogRow

    backend.egress_rows.append(
        EgressLogRow(
            timestamp_ms=1_000,
            engagement_id="e1",
            processor_name="deepgram",
            region="us",
            byte_count=128,
            success=True,
        )
    )

    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "e1", "start_ms": 0, "end_ms": 2_000},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_egress_audit_log_end_before_start_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/audit/egress",
        params={"engagement_id": "e1", "start_ms": 2_000, "end_ms": 0},
    )

    assert response.status_code == 422
