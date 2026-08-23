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
    # A window short enough to read to the end. The connection is held open
    # for minutes in a deployment, which is the point of it — a test that took
    # the deployment's window would take the deployment's window.
    app.include_router(
        _stream.build_session_stream_router(events, heartbeat_seconds=0.01, hold_seconds=0.02)
    )
    return TestClient(app)


def _backlog(response) -> str:
    """Everything the stream has to say right now, as a body.

    The connection is held open after the backlog, so a reader that waits for
    the last byte waits for the whole hold window. The first comment frame is
    the stream's own mark for "that is all there is for now", and stopping
    there is what makes the backlog a finite thing to assert about.
    """

    lines: list[str] = []
    for line in response.iter_lines():
        if line.startswith(":"):
            break
        lines.append(line)
    return "\n".join(lines)


def test_a_frame_ends_with_a_blank_line() -> None:
    """Without it the client buffers forever and the panel silently never updates."""

    frame = _stream.format_sse("nudge", {"id": "n1"})

    assert frame.startswith("event: nudge\n")
    assert frame.endswith("\n\n")


def test_the_stream_is_announced_as_server_sent_events() -> None:
    async def events(meeting_id: str):
        if False:
            yield

    with _client(events).stream("GET", "/api/meetings/m1/session/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


def test_buffering_is_disabled_so_a_meeting_is_not_delivered_at_the_end_of_it() -> None:
    async def events(meeting_id: str):
        if False:
            yield

    with _client(events).stream("GET", "/api/meetings/m1/session/stream") as response:
        headers = response.headers

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

    with _client(events).stream("GET", "/api/meetings/m1/session/stream") as response:
        body = _backlog(response)

    assert body.index("event: coverage") < body.index("event: nudge")
    assert '"stub": "How fast is fast?"' in body


def test_the_stream_carries_the_meeting_it_was_asked_for() -> None:
    seen: list[str] = []

    async def events(meeting_id: str):
        seen.append(meeting_id)
        if False:
            yield

    # Read one frame rather than none: `events` is not called until the
    # response body is first iterated, so a request whose body nobody touches
    # proves nothing about which meeting was asked for.
    with _client(events).stream("GET", "/api/meetings/meeting-42/session/stream") as response:
        _backlog(response)

    assert seen == ["meeting-42"]


def test_the_lane_state_arrives_before_anything_it_qualifies(monkeypatch) -> None:
    """The panel has to know which mode it is in before it renders a suggestion.

    A quiet panel means "nothing to say" in full mode and "the model is
    unreachable" in degraded mode. An operator shown suggestions before being
    told which mode produced them has been given no way to tell those apart.
    """

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    monkeypatch.setenv(_stream.HOLD_SECONDS_ENV, "0.02")
    backend = Backend()
    backend.session_stream_events["meeting-1"] = [
        ("coverage", {"slots": [], "time_remaining_ms": None}),
    ]
    app = build_app(backend)

    with TestClient(app) as client:
        with client.stream("GET", "/api/meetings/meeting-1/session/stream") as response:
            assert response.status_code == 200
            body = _backlog(response)

    events = [line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "lane", f"lane must lead the stream, got {events}"
    assert "coverage" in events


def test_an_unconfigured_provider_is_reported_as_degraded_with_a_reason(monkeypatch) -> None:
    import json

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    monkeypatch.setenv(_stream.HOLD_SECONDS_ENV, "0.02")
    with TestClient(build_app(Backend())) as client:
        with client.stream("GET", "/api/meetings/meeting-1/session/stream") as response:
            body = _backlog(response)

    lane = json.loads(body.split("event: lane\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert lane["model_reachable"] is False
    # Names what to do about it, rather than only that something is wrong.
    assert "Settings" in lane["reason"]


def test_the_stream_stays_open_after_delivering_what_it_has() -> None:
    """A stream that ends is a stream the panel reconnects to every three seconds.

    `EventSource` treats a completed response as a dropped connection and
    retries on its own timer — so a generator that returns the moment it has
    nothing left to say turns one long-lived subscription into a poll of
    roughly twelve hundred connections an hour, each re-sending the lane and
    language frames the panel already had. It also loses anything produced
    between two connections, which is the half of this that would bite once
    something actually raises a nudge.

    The comment frame is what makes "nothing more for now" observable without
    ending the response: `EventSource` ignores a line beginning with a colon,
    and an intermediary counts it as traffic and leaves the connection alone.
    """

    async def events(meeting_id: str):
        yield "coverage", {"slots": [], "time_remaining_ms": None}

    app = FastAPI()
    app.include_router(
        _stream.build_session_stream_router(events, heartbeat_seconds=0.01, hold_seconds=0.05)
    )

    with TestClient(app) as client:
        with client.stream("GET", "/api/meetings/m1/session/stream") as response:
            lines = [line for line in response.iter_lines()]

    assert any(line.startswith(":") for line in lines), (
        "the stream ended after its backlog instead of staying open; "
        f"the panel will reconnect on EventSource's own timer. Got: {lines}"
    )


def test_a_held_connection_is_still_closed_rather_than_held_for_ever() -> None:
    """Something in front of this recycles connections whether we plan for it or not.

    A body with no end cannot be read to completion by a proxy, a diagnostic
    or a test, and the client already knows how to reopen one — so the hold is
    a window rather than a promise. What it must not be is the window this had
    before, which was no window at all: drain and close, three seconds later
    do it again.
    """

    async def events(meeting_id: str):
        if False:
            yield

    app = FastAPI()
    app.include_router(
        _stream.build_session_stream_router(events, heartbeat_seconds=0.01, hold_seconds=0.05)
    )

    with TestClient(app) as client:
        with client.stream("GET", "/api/meetings/m1/session/stream") as response:
            beats = [line for line in response.iter_lines() if line.startswith(":")]

    assert len(beats) > 1, (
        f"the connection was not held open across a heartbeat: {beats}"
    )


def test_an_event_produced_after_the_connection_opened_still_reaches_the_panel() -> None:
    """The whole reason the connection is held: a nudge is raised mid-meeting.

    A backlog-only stream can carry what the meeting had queued when the panel
    connected, which is nothing at all in the first seconds of a meeting. The
    events a panel exists to show are all produced later.
    """

    async def events(meeting_id: str):
        yield "coverage", {"slots": [], "time_remaining_ms": None}
        # Nothing to say yet — the shape a live source has while the room is
        # quiet, and the point at which the old stream gave up and closed.
        yield None
        yield "nudge", {
            "id": "n1",
            "stub": "In numbers?",
            "question": "What response time would you consider a failure?",
            "trigger_reason": 'unquantified adjective — "fast"',
            "created_at": 1,
        }

    app = FastAPI()
    app.include_router(
        _stream.build_session_stream_router(events, heartbeat_seconds=0.01, hold_seconds=0.05)
    )

    with TestClient(app) as client:
        body = client.get("/api/meetings/m1/session/stream").text

    assert "event: nudge" in body
    assert body.index("event: coverage") < body.index("event: nudge")


def test_a_quiet_source_is_reported_as_quiet_rather_than_as_an_event() -> None:
    """`None` is "still here, nothing to say", and must not reach the panel as data.

    An `EventSource` ignores a comment frame, so a quiet meeting costs the
    panel nothing. A frame carrying an empty payload would instead be parsed,
    dispatched, and rendered as a nudge with no question in it.
    """

    async def events(meeting_id: str):
        yield None
        yield None

    app = FastAPI()
    app.include_router(
        _stream.build_session_stream_router(events, heartbeat_seconds=0.01, hold_seconds=0.02)
    )

    with TestClient(app) as client:
        body = client.get("/api/meetings/m1/session/stream").text

    assert "event:" not in body
    assert body.count(": keep-alive") >= 2
