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
