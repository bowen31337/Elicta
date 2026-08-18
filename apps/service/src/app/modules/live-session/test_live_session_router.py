"""Tests for the live capture session start HTTP surface (PRD "Live Session" domain).

Loaded via `importlib.import_module` with the full dotted path rather than
`from .models import ...` / `from .router import ...`: this package's
directory (`live-session`) is not a valid Python identifier, and pytest's
default test-collection import mode cannot resolve a relative import inside
it (it works fine at real runtime via `app.module_loader`, which uses the
same `importlib.import_module` mechanism this file uses).
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

_models = importlib.import_module("app.modules.live-session.models")
_router = importlib.import_module("app.modules.live-session.router")

SessionStart = _models.SessionStart
build_live_session_router = _router.build_live_session_router


def make_client(
    known_meetings: set[str] | None = None,
) -> tuple[TestClient, list[str]]:
    known_ids = known_meetings if known_meetings is not None else {"meeting-1"}
    received: list[str] = []

    async def start_session(meeting_id: str):
        received.append(meeting_id)
        if meeting_id not in known_ids:
            return None
        return SessionStart(
            session_id="session-1",
            meeting_id=meeting_id,
            started_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        )

    app = FastAPI()
    app.include_router(build_live_session_router(start_session))
    return TestClient(app), received


def test_starting_a_session_returns_200_with_a_session_id():
    client, _ = make_client(known_meetings={"meeting-1"})

    response = client.post("/api/meetings/meeting-1/session/start")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["meeting_id"] == "meeting-1"
    assert body["started_at"] == "2026-08-19T09:00:00Z"


def test_starting_a_session_passes_the_meeting_id_through():
    client, received = make_client(known_meetings={"meeting-1"})

    client.post("/api/meetings/meeting-1/session/start")

    assert received == ["meeting-1"]


def test_starting_a_session_for_an_unknown_meeting_returns_404():
    client, _ = make_client(known_meetings=set())

    response = client.post("/api/meetings/does-not-exist/session/start")

    assert response.status_code == 404
