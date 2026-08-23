"""The live lane, end to end: an utterance goes in, a nudge reaches the panel.

This is the seam the whole product is named for, and it was empty. The panel,
the stream, the bank and the disposition route all existed and were tested;
nothing joined them, so a real meeting produced a panel that sat at its
resting state from the first word to the last.

Driven through the production composition root, so what is asserted here is
the assembly that ships.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _frames(client: TestClient, meeting_id: str) -> list[tuple[str, dict]]:
    """The stream's frames, up to the point it has nothing more to say."""

    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        lines = []
        for line in response.iter_lines():
            if line.startswith(":"):
                break
            lines.append(line)

    frames: list[tuple[str, dict]] = []
    name: str | None = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            frames.append((name, json.loads(line.removeprefix("data: "))))
            name = None
    return frames


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


def test_a_vague_answer_becomes_a_nudge_on_the_panel_stream(client: TestClient) -> None:
    """The journey the product exists for, joined up for the first time."""

    meeting_id = _meeting(client)

    observed = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast.", "speaker": "client"},
    )
    assert observed.status_code == 202, observed.text
    assert observed.json()["triggered"] is True
    assert observed.json()["surfaced"] is True

    nudges = [payload for name, payload in _frames(client, meeting_id) if name == "nudge"]

    assert len(nudges) == 1, f"expected one nudge on the stream, got {nudges}"
    assert nudges[0]["trigger_reason"] == 'unquantified adjective — "fast"'
    assert nudges[0]["question"]
    assert nudges[0]["stub"]


def test_an_ordinary_sentence_puts_nothing_on_the_panel(client: TestClient) -> None:
    """FR-5.7 from the operator's side: most of a meeting must stay quiet."""

    meeting_id = _meeting(client)

    observed = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "We run three hundred and fifty consignments a day."},
    )
    assert observed.status_code == 202, observed.text
    assert observed.json()["triggered"] is False

    assert [name for name, _ in _frames(client, meeting_id) if name == "nudge"] == []


def test_a_second_vague_answer_inside_a_minute_does_not_interrupt_again(
    client: TestClient,
) -> None:
    """FR-5.8, at the seam rather than in the unit that implements it."""

    meeting_id = _meeting(client)

    for text in ("The dashboard has to be fast.", "And the depot flow should be flexible."):
        observed = client.post(
            f"/api/meetings/{meeting_id}/live/utterance", json={"text": text}
        )
        assert observed.status_code == 202, observed.text

    nudges = [payload for name, payload in _frames(client, meeting_id) if name == "nudge"]

    assert len(nudges) == 1, f"the rate limit let a second nudge through: {nudges}"


def test_the_operator_can_dispose_of_a_nudge_the_gate_raised(client: TestClient) -> None:
    """The panel's one-tap responses post against the id the stream carried.

    A nudge whose id the disposition route rejects would leave every chip on
    the panel answering 404 -- the operator taps, nothing happens, and the
    debrief never learns which suggestions were used.
    """

    meeting_id = _meeting(client)
    client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast."},
    )
    nudge = next(
        payload for name, payload in _frames(client, meeting_id) if name == "nudge"
    )

    recorded = client.post(
        f"/api/meetings/{meeting_id}/nudges/{nudge['id']}/disposition",
        json={"disposition": "taken"},
    )

    assert recorded.status_code == 200, recorded.text


def test_an_utterance_for_a_meeting_that_does_not_exist_is_refused(client: TestClient) -> None:
    assert (
        client.post("/api/meetings/meeting-404/live/utterance", json={"text": "fast"}).status_code
        == 404
    )


def test_uploaded_audio_becomes_a_nudge_without_anything_else_being_called(
    backend, settings_store
) -> None:
    """The join the product was missing, from the bytes the capture screen sends.

    Everything either side of this was built and tested before: the capture
    screen uploads chunks, the gate reads utterances, the stream carries
    nudges. Nothing turned the first into the second, so a meeting recorded
    perfectly and left the panel at its resting state throughout.

    The recogniser is injected, which is the only reason this can be asserted
    at all: the vendor-backed one needs a speech credential and bills per
    call, and a seam that could only be exercised by buying one is a seam that
    would go back to being exercised by nobody.
    """

    import base64

    from app.composition import build_app

    async def recognise(session_id: str, pcm: bytes) -> str:
        return "The dashboard just has to be fast."

    app = build_app(backend, settings_store=settings_store, live_recogniser=recognise)

    with TestClient(app) as client:
        meeting_id = _meeting(client)
        assert client.post(f"/api/meetings/{meeting_id}/session/start").status_code == 200

        # One window's worth of linear16 at 16kHz mono, which is what the
        # capture screen's uploader states it sends.
        window = base64.b64encode(b"\x00" * (32_000 * 4)).decode()
        uploaded = client.post(
            f"/api/sessions/{meeting_id}/audio-chunk", json={"sequence": 0, "pcm": window}
        )
        assert uploaded.status_code == 202, uploaded.text

        nudges = [payload for name, payload in _frames(client, meeting_id) if name == "nudge"]

    assert len(nudges) == 1, f"uploaded audio raised no nudge: {nudges}"
    assert nudges[0]["trigger_reason"] == 'unquantified adjective — "fast"'


def test_audio_too_short_to_be_worth_recognising_is_not_sent_anywhere(
    backend, settings_store
) -> None:
    """Every call is billed, and a meeting is mostly fractions of a second."""

    import base64

    from app.composition import build_app

    asked: list[bytes] = []

    async def recognise(session_id: str, pcm: bytes) -> str:
        asked.append(pcm)
        return "The dashboard just has to be fast."

    app = build_app(backend, settings_store=settings_store, live_recogniser=recognise)

    with TestClient(app) as client:
        meeting_id = _meeting(client)
        client.post(
            f"/api/sessions/{meeting_id}/audio-chunk",
            json={"sequence": 0, "pcm": base64.b64encode(b"\x00" * 1_600).decode()},
        )

    assert asked == []


def test_the_operator_can_park_a_nudge_for_the_debrief(client: TestClient) -> None:
    """FR-6.8's `Park it`: not now, but do not lose it.

    The panel offers the chip against every surfaced nudge and posts to
    `/api/threads/{id}/park`, which nothing served — so the one response an
    operator gives when a question is worth asking later answered 404, and the
    thread was lost rather than deferred.
    """

    meeting_id = _meeting(client)
    client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast."},
    )
    nudge = next(payload for name, payload in _frames(client, meeting_id) if name == "nudge")

    parked = client.post(f"/api/threads/{nudge['id']}/park", json={})

    assert parked.status_code == 200, parked.text
    assert parked.json()["open_question_id"]


def test_a_parked_question_reaches_the_engagement_it_was_asked_in(client: TestClient) -> None:
    """Parking that recorded nothing would be a chip that only looks like it works."""

    meeting_id = _meeting(client)
    client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast."},
    )
    nudge = next(payload for name, payload in _frames(client, meeting_id) if name == "nudge")
    client.post(f"/api/threads/{nudge['id']}/park", json={})

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.status_code == 200, detail.text
    engagement_id = detail.json()["engagement_id"]
    state = client.get(f"/api/engagements/{engagement_id}/state")

    assert state.status_code == 200, state.text
    assert any(
        "fast" in question["text"] for question in state.json()["inherited_open_questions"]
    ), state.text


def test_going_deeper_offers_another_question_about_the_same_thing(client: TestClient) -> None:
    """FR-6.8's `Go deeper`: that answer opened something, follow it."""

    meeting_id = _meeting(client)
    client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast."},
    )
    nudge = next(payload for name, payload in _frames(client, meeting_id) if name == "nudge")

    deeper = client.post(f"/api/threads/{nudge['id']}/go-deeper", json={})

    assert deeper.status_code == 200, deeper.text
    followed = deeper.json()["question"]
    assert followed
    assert followed != nudge["question"], "going deeper returned the question already asked"


def test_a_thread_nobody_raised_is_not_found(client: TestClient) -> None:
    """A made-up id must not quietly produce a question about nothing."""

    assert client.post("/api/threads/nudge-404/park", json={}).status_code == 404
    assert client.post("/api/threads/nudge-404/go-deeper", json={}).status_code == 404


def test_a_meeting_from_before_a_restart_still_has_its_bank(client: TestClient, backend) -> None:
    """The join from meeting to engagement has a durable half, and must use it.

    `meeting_engagement_ids` is written when a meeting is created and lives in
    memory, so a process that restarts knows nothing about any meeting the one
    before it made. The meeting's own row carries the same fact durably, and
    `_engagement_of_meeting` exists to consult both -- but the bank lookup read
    the dict directly.

    The symptom is quiet and easy to misread: every nudge in a restarted
    service falls back to templated wording, because the bank it should have
    selected from resolves empty. It reads as a bank that was never compiled.
    """

    meeting_id = _meeting(client)
    # What a restart leaves behind: the durable row, and nothing in memory.
    backend.meeting_engagement_ids.clear()

    bank = client.get(f"/api/meetings/{meeting_id}/bank")

    assert bank.status_code == 200, bank.text
    # The engagement here has no compiled candidates, so the assertion that
    # carries this is the join being attempted at all rather than short-
    # circuiting on a missing id.
    observed = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast."},
    )
    assert observed.status_code == 202, observed.text
    nudge = next(payload for name, payload in _frames(client, meeting_id) if name == "nudge")

    parked = client.post(f"/api/threads/{nudge['id']}/park", json={})

    assert parked.status_code == 200, (
        "parking fell through the same in-memory join and answered 404: " + parked.text
    )


def test_the_meeting_being_recorded_can_be_found_from_outside_the_browser(
    client: TestClient,
) -> None:
    """Which meeting has a microphone open, answered from evidence.

    The panel and the capture screen keep their meeting in the browser's own
    storage, where nothing else can reach it, and the service could not answer
    either: sessions are started and never ended, and a meeting's state stays
    `planned` while it is being recorded. So a second window, or any tool
    outside the browser, had to be told the meeting by hand.
    """

    import base64

    quiet = _meeting(client)
    recording = _meeting(client)
    for meeting_id in (quiet, recording):
        assert client.post(f"/api/meetings/{meeting_id}/session/start").status_code == 200

    client.post(
        f"/api/sessions/{recording}/audio-chunk",
        json={"sequence": 0, "pcm": base64.b64encode(b"\x00" * 3_200).decode()},
    )

    live = client.get("/api/sessions/live")

    assert live.status_code == 200, live.text
    sessions = live.json()["sessions"]
    assert sessions[0]["meeting_id"] == recording, sessions
    assert sessions[0]["receiving_audio"] is True
    # The one that was started and heard nothing is reported, and is not
    # claimed to be recording — pressing Start with a microphone that reads
    # nothing is exactly this, and it is worth being able to see.
    started_only = next(row for row in sessions if row["meeting_id"] == quiet)
    assert started_only["receiving_audio"] is False
    assert started_only["last_audio_at"] is None
