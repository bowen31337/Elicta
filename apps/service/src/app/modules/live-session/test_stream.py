"""The live session stream.

Two properties carry this module: the frame format the browser's EventSource
requires, and that a coverage update reaches the panel as the *current*
summary rather than as a diff to apply.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

_stream = importlib.import_module("app.modules.live-session.stream")


def _client(events) -> TestClient:
    app = FastAPI()
    app.include_router(_stream.build_session_stream_router(events))
    return TestClient(app)


def test_a_frame_ends_with_a_blank_line() -> None:
    """Without it the client buffers forever and the panel silently never updates."""

    frame = _stream.format_sse("nudge", {"id": "n1"})

    assert frame.startswith("event: nudge\n")
    assert frame.endswith("\n\n")


def test_the_stream_is_announced_as_server_sent_events() -> None:
    async def events(meeting_id: str):
        if False:
            yield

    response = _client(events).get("/api/meetings/m1/session/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_buffering_is_disabled_so_a_meeting_is_not_delivered_at_the_end_of_it() -> None:
    async def events(meeting_id: str):
        if False:
            yield

    headers = _client(events).get("/api/meetings/m1/session/stream").headers

    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"


def test_coverage_and_nudges_arrive_in_the_order_they_were_produced() -> None:
    async def events(meeting_id: str):
        yield "coverage", {
            "slots": [{"id": "performance", "label": "Performance", "filled": False}],
            "time_remaining_ms": 1_200_000,
        }
        yield "nudge", {
            "id": "n1",
            "stub": "How fast is fast?",
            "question": "What does fast mean in seconds?",
            "trigger_reason": 'unquantified adjective — "fast"',
            "created_at": 1,
        }

    body = _client(events).get("/api/meetings/m1/session/stream").text

    assert body.index("event: coverage") < body.index("event: nudge")
    assert '"stub": "How fast is fast?"' in body


def test_the_stream_carries_the_meeting_it_was_asked_for() -> None:
    seen: list[str] = []

    async def events(meeting_id: str):
        seen.append(meeting_id)
        if False:
            yield

    _client(events).get("/api/meetings/meeting-42/session/stream")

    assert seen == ["meeting-42"]


def test_the_lane_state_arrives_before_anything_it_qualifies() -> None:
    """The panel has to know which mode it is in before it renders a suggestion.

    A quiet panel means "nothing to say" in full mode and "the model is
    unreachable" in degraded mode. An operator shown suggestions before being
    told which mode produced them has been given no way to tell those apart.
    """

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    backend = Backend()
    backend.session_stream_events["meeting-1"] = [
        ("coverage", {"slots": [], "time_remaining_ms": None}),
    ]
    app = build_app(backend)

    with TestClient(app) as client:
        with client.stream("GET", "/api/meetings/meeting-1/session/stream") as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    events = [line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "lane", f"lane must lead the stream, got {events}"
    assert "coverage" in events


def test_an_unconfigured_provider_is_reported_as_degraded_with_a_reason() -> None:
    import json

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    with TestClient(build_app(Backend())) as client:
        with client.stream("GET", "/api/meetings/meeting-1/session/stream") as response:
            body = "".join(response.iter_text())

    lane = json.loads(body.split("event: lane\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert lane["model_reachable"] is False
    # Names what to do about it, rather than only that something is wrong.
    assert "Settings" in lane["reason"]
