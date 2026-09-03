"""The Stop button on the panel ends the recording.

It did not. `POST /api/meetings/{id}/session/stop` is what the panel's
recording bar has posted to since the bar was added, and the service has never
served that path — the live-session router carried `session/start` and nothing
else. Every press was a 404, which `useStopSession` turned into an `error`
status that no part of the panel renders, so the bar simply stayed on
"Recording" with the clock running. The operator's only signal that they had
pressed anything was the absence of one.

The client half was fully unit-tested throughout. `stopSession.test.ts` drives
it with a stubbed `fetch`, and a stub answers whatever URL it is handed — so a
green suite said nothing about whether the route existed. Two doc comments in
the desktop describe this endpoint in the present tense, one of them reasoning
about what it does to a meeting ("the only endpoint that ends a session also
writes a coverage summary and marks the meeting over"). Written about nothing.

Which is why this file is here rather than only beside the router: it drives
the production composition root, so what it asserts is the assembly that ships
and the route table it actually mounts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "logistics",
            "commercial_context": "Discovery",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _live_meetings(client: TestClient) -> list[str]:
    listed = client.get("/api/sessions/live")
    assert listed.status_code == 200, listed.text
    return [session["meeting_id"] for session in listed.json()["sessions"]]


def test_the_route_the_panel_posts_to_is_actually_mounted(client: TestClient) -> None:
    """The whole bug, in one assertion.

    Asked of the served schema rather than by making a request, because that
    is the check that was missing: the panel had a caller, the caller had
    tests, and nothing anywhere compared the path it posts to against the
    paths the service answers on.
    """

    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/meetings/{meeting_id}/session/stop" in paths
    assert "post" in paths["/api/meetings/{meeting_id}/session/stop"]


def test_stopping_ends_the_session_and_the_meeting_stops_being_listed_as_live(
    client: TestClient,
) -> None:
    meeting_id = _meeting(client)
    started = client.post(f"/api/meetings/{meeting_id}/session/start")
    assert started.status_code == 200, started.text
    assert meeting_id in _live_meetings(client)

    stopped = client.post(f"/api/meetings/{meeting_id}/session/stop")

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["session_id"] == started.json()["session_id"]
    assert stopped.json()["meeting_id"] == meeting_id
    # The reading that matters to anyone else: "what is being recorded right
    # now" no longer includes this meeting. A stop that returned 200 and left
    # the meeting listed would be the same failure with a better status code.
    assert meeting_id not in _live_meetings(client)


def test_stopping_a_meeting_that_was_never_started_still_succeeds(
    client: TestClient,
) -> None:
    """Nothing open is the state the operator asked for.

    A 404 or a 409 here would put the button back where it started — pressed,
    and visibly doing nothing — for the case where the panel and the service
    disagree about whether a session is open, which is exactly when an
    operator reaches for it.
    """

    meeting_id = _meeting(client)

    stopped = client.post(f"/api/meetings/{meeting_id}/session/stop")

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["session_id"] is None
    assert stopped.json()["meeting_id"] == meeting_id


def test_stopping_twice_is_not_an_error(client: TestClient) -> None:
    meeting_id = _meeting(client)
    client.post(f"/api/meetings/{meeting_id}/session/start")

    first = client.post(f"/api/meetings/{meeting_id}/session/stop")
    second = client.post(f"/api/meetings/{meeting_id}/session/stop")

    assert first.json()["session_id"] is not None
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] is None


def test_stopping_an_unknown_meeting_is_a_404(client: TestClient) -> None:
    stopped = client.post("/api/meetings/meeting-that-does-not-exist/session/stop")

    assert stopped.status_code == 404


def test_starting_again_after_a_stop_opens_a_new_session(client: TestClient) -> None:
    """A meeting stopped and restarted is one recording at a time.

    `start_session` already ended any session it found open, for a bug where a
    recorder that stopped and started again showed up as two meetings being
    recorded at once. Stopping now ends one too, so the two paths agree — and
    the second start must still hand back a session of its own rather than
    resurrecting the one that was closed.
    """

    meeting_id = _meeting(client)
    first = client.post(f"/api/meetings/{meeting_id}/session/start").json()
    client.post(f"/api/meetings/{meeting_id}/session/stop")

    second = client.post(f"/api/meetings/{meeting_id}/session/start")

    assert second.status_code == 200, second.text
    assert second.json()["session_id"] != first["session_id"]
    assert _live_meetings(client).count(meeting_id) == 1


def test_a_body_from_an_older_panel_does_not_break_the_stop(client: TestClient) -> None:
    """The coverage flush the panel used to send.

    Coverage is derived in the service now, from the meeting's own nudge
    dispositions, so there is nothing here for a client's copy to be
    authoritative about. A build that still sends one must still stop cleanly
    rather than meeting a 422.
    """

    meeting_id = _meeting(client)
    client.post(f"/api/meetings/{meeting_id}/session/start")

    stopped = client.post(
        f"/api/meetings/{meeting_id}/session/stop",
        json={"coverage": {"slots": [], "time_remaining_ms": 900_000}},
    )

    assert stopped.status_code == 200, stopped.text
    assert meeting_id not in _live_meetings(client)
