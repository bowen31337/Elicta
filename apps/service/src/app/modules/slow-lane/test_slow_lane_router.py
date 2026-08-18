"""Tests for accepting a slow-lane tick over HTTP (PRD FR-5.10; architecture §3.8).

Covers `POST /api/meetings/{meeting_id}/slow-lane/tick`.

Loaded via `importlib.import_module` with the full dotted path rather than
`from .models import ...` / `from .router import ...`: this package's
directory (`slow-lane`) is not a valid Python identifier, and pytest's
default test-collection import mode cannot resolve a relative import inside
it (it works fine at real runtime via `app.module_loader`, which uses the
same `importlib.import_module` mechanism this file uses) -- same reasoning
as `app/modules/live-session/test_live_session_router.py`.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

_models = importlib.import_module("app.modules.slow-lane.models")
_router = importlib.import_module("app.modules.slow-lane.router")

FillState = _models.FillState
CoverageSlotUpdate = _models.CoverageSlotUpdate
SlowLaneCandidate = _models.SlowLaneCandidate
SlowLaneTickResult = _models.SlowLaneTickResult
build_slow_lane_tick_router = _router.build_slow_lane_tick_router


def make_client(
    known_meetings: set[str] | None = None,
) -> tuple[TestClient, list[str]]:
    known_ids = known_meetings if known_meetings is not None else {"meeting-1"}
    received: list[str] = []

    async def run_tick(meeting_id: str):
        received.append(meeting_id)
        if meeting_id not in known_ids:
            return None
        return SlowLaneTickResult(
            meeting_id=meeting_id,
            coverage_updates=[
                CoverageSlotUpdate(
                    template_section="scope",
                    fill_state=FillState.FILLED,
                    satisfied_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
                )
            ],
            new_candidates=[
                SlowLaneCandidate(
                    id="candidate-1",
                    template_section="risks",
                    phrasing="What happens if the vendor misses the deadline?",
                    priority=1,
                )
            ],
            ticked_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        )

    app = FastAPI()
    app.include_router(build_slow_lane_tick_router(run_tick))
    return TestClient(app), received


def test_accepting_a_tick_returns_200_with_coverage_updates_and_new_candidates():
    client, _ = make_client(known_meetings={"meeting-1"})

    response = client.post("/api/meetings/meeting-1/slow-lane/tick")

    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert body["coverage_updates"] == [
        {
            "template_section": "scope",
            "fill_state": "filled",
            "satisfied_at": "2026-08-19T09:00:00Z",
        }
    ]
    assert body["new_candidates"] == [
        {
            "id": "candidate-1",
            "template_section": "risks",
            "phrasing": "What happens if the vendor misses the deadline?",
            "priority": 1,
        }
    ]
    assert body["ticked_at"] == "2026-08-19T09:00:00Z"


def test_accepting_a_tick_passes_the_meeting_id_through():
    client, received = make_client(known_meetings={"meeting-1"})

    client.post("/api/meetings/meeting-1/slow-lane/tick")

    assert received == ["meeting-1"]


def test_a_tick_with_no_coverage_changes_or_new_candidates_still_returns_200():
    async def run_tick(meeting_id: str):
        return SlowLaneTickResult(
            meeting_id=meeting_id,
            coverage_updates=[],
            new_candidates=[],
            ticked_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        )

    app = FastAPI()
    app.include_router(build_slow_lane_tick_router(run_tick))
    client = TestClient(app)

    response = client.post("/api/meetings/meeting-1/slow-lane/tick")

    assert response.status_code == 200
    body = response.json()
    assert body["coverage_updates"] == []
    assert body["new_candidates"] == []


def test_accepting_a_tick_for_an_unknown_meeting_returns_404():
    client, _ = make_client(known_meetings=set())

    response = client.post("/api/meetings/does-not-exist/slow-lane/tick")

    assert response.status_code == 404
