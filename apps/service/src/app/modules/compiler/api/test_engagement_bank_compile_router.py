"""Tests for triggering an engagement's bank compile (PRD FR-4.8).

Covers `POST /api/engagements/{id}/bank/compile`: accepts the request and
returns 202 with a `job_id` handle for the triggered compile job.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.compiler.api.router import build_engagement_bank_compile_router


def make_client(job_id: str = "job-123") -> tuple[TestClient, list[str]]:
    triggered: list[str] = []

    async def trigger_bank_compile(engagement_id: str) -> str:
        triggered.append(engagement_id)
        return job_id

    app = FastAPI()
    app.include_router(build_engagement_bank_compile_router(trigger_bank_compile))
    return TestClient(app), triggered


def test_post_engagement_bank_compile_returns_202_with_a_job_id():
    client, triggered = make_client(job_id="job-abc")

    response = client.post("/api/engagements/engagement-1/bank/compile")

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "job-abc"
    assert body["engagement_id"] == "engagement-1"
    assert "triggered_at" in body
    assert triggered == ["engagement-1"]


def test_post_engagement_bank_compile_passes_the_path_engagement_id_through():
    client, triggered = make_client()

    response = client.post("/api/engagements/engagement-42/bank/compile")

    assert response.status_code == 202
    assert response.json()["engagement_id"] == "engagement-42"
    assert triggered == ["engagement-42"]
