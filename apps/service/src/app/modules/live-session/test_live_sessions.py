"""Which meeting is being recorded right now.

Nothing could answer this. A session is started and never ended -- there is no
stop route -- so the set of started sessions grows for the life of the process
and says nothing about which one has a microphone open. A meeting's own state
stays `planned` throughout. So a tool outside the browser had no way to find
the meeting an operator was sitting in front of, and neither did an operator
with two windows open.

The evidence this answers from is audio arriving, because that is the only
thing that distinguishes a meeting being recorded from one that was started an
hour ago and abandoned. It reports what it saw and when, rather than a verdict
with no grounds: `receiving_audio` is a reading of the clock against the last
chunk, and a caller that disagrees about the window can use the timestamp.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

_sessions = importlib.import_module("app.modules.live-session.sessions")

NOW = datetime(2026, 8, 24, 9, 0, 0, tzinfo=UTC)


def _client(rows) -> TestClient:
    app = FastAPI()
    app.include_router(_sessions.build_live_sessions_router(lambda: rows, now=lambda: NOW))
    return TestClient(app)


def _row(session_id: str, meeting_id: str, seconds_ago: float | None):
    return {
        "session_id": session_id,
        "meeting_id": meeting_id,
        "started_at": NOW - timedelta(minutes=5),
        "last_audio_at": None if seconds_ago is None else NOW - timedelta(seconds=seconds_ago),
    }


def test_a_session_taking_audio_now_is_reported_as_receiving_it() -> None:
    body = _client([_row("session-1", "meeting-9", seconds_ago=2)]).get("/api/sessions/live").json()

    assert body["sessions"][0]["meeting_id"] == "meeting-9"
    assert body["sessions"][0]["receiving_audio"] is True


def test_a_session_that_has_gone_quiet_is_not_claimed_to_be_live() -> None:
    """The abandoned case, which is most of them: started, walked away from."""

    body = _client([_row("session-1", "meeting-9", seconds_ago=600)]).get("/api/sessions/live").json()

    assert body["sessions"][0]["receiving_audio"] is False


def test_a_session_that_never_took_any_audio_says_so() -> None:
    """Pressing Start and getting no microphone is exactly this, and it happened."""

    body = _client([_row("session-1", "meeting-9", seconds_ago=None)]).get("/api/sessions/live").json()

    assert body["sessions"][0]["receiving_audio"] is False
    assert body["sessions"][0]["last_audio_at"] is None


def test_the_one_with_the_freshest_audio_is_first() -> None:
    """A caller wanting "the meeting being recorded" should not have to sort."""

    rows = [
        _row("session-1", "meeting-1", seconds_ago=90),
        _row("session-2", "meeting-2", seconds_ago=1),
        _row("session-3", "meeting-3", seconds_ago=None),
    ]

    body = _client(rows).get("/api/sessions/live").json()

    assert [row["meeting_id"] for row in body["sessions"]] == ["meeting-2", "meeting-1", "meeting-3"]


def test_no_sessions_is_an_empty_list_rather_than_an_error() -> None:
    assert _client([]).get("/api/sessions/live").json() == {"sessions": []}
