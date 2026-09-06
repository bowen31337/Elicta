"""Clicking Capture puts the room's words on the panel.

The join this asserts is the one thing about the live lane that nothing
tested. The pieces each have their own tests: the chunk upload holds audio in
order, `LiveUtterances` buffers a window and recognises it, the gate decides
whether a question is worth raising, and the stream carries what it is given.
Between them runs a value that five hops call `session_id` — the route, the
`on_chunk` callback, `feed_live_lane`, `LiveUtterances.feed`, `_observe_text` —
and the sixth hop hands it to a parameter called `meeting_id`, which drops
anything that is not a known meeting.

It lines up only because `chunkUploader.ts` posts the **meeting** id into
`/api/sessions/{id}/audio-chunk`. That is load-bearing and it is a
coincidence of naming: resolve a real `session-N` id anywhere along that
chain — which the names invite — and `observe_utterance` returns `None` for
every window of every meeting. No error, no log line, no nudge and no
transcript; the panel simply sits at its resting state, which is the exact
failure this product has already shipped twice.

Driven through the production composition root, over the routes the capture
screen actually walks.
"""

from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.trigger.listener import WINDOW_BYTES

#: A whole window. The lane recognises windows rather than chunks, so a short
#: chunk is buffered and nothing reaches the recogniser at all — which looks
#: identical to a broken join and would let this file pass either way.
WINDOW = base64.b64encode(b"\x00\x01" * (WINDOW_BYTES // 2)).decode()


def _app_hearing(said: list[str]) -> TestClient:
    """An app whose live lane hears `said`, one line per window."""

    heard = iter(said)

    async def recognise(session_id: str, pcm: bytes) -> str:
        return next(heard, "")

    return TestClient(build_app(Backend(), live_recogniser=recognise))


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


def _capture(client: TestClient, meeting_id: str, windows: int) -> None:
    """What the capture screen does: open a recording, then upload chunks.

    Addressed by **meeting** id, because that is what `chunkUploader.ts` puts
    in the path. The route calls it a session id and so does everything behind
    it; this is the line where those two names have to mean the same thing.
    """

    opened = client.post(f"/api/sessions/{meeting_id}/recording", json={})
    assert opened.status_code in (200, 201), opened.text
    for sequence in range(windows):
        sent = client.post(
            f"/api/sessions/{meeting_id}/audio-chunk",
            json={"sequence": sequence, "pcm": WINDOW},
        )
        assert sent.status_code in (200, 202), sent.text


def _utterances(client: TestClient, meeting_id: str) -> list[dict]:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        lines = []
        for line in response.iter_lines():
            if line.startswith(":"):
                break
            lines.append(line)

    frames: list[dict] = []
    name: str | None = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            if name == "utterance":
                frames.append(json.loads(line.removeprefix("data: ")))
            name = None
    return frames


def test_uploaded_audio_reaches_the_panel_as_transcript() -> None:
    """The whole point: capture starts, and the panel shows what was said."""

    client = _app_hearing(["We run three hundred and fifty consignments a day."])
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=1)

    assert [u["text"] for u in _utterances(client, meeting_id)] == [
        "We run three hundred and fifty consignments a day."
    ]


def test_a_line_that_earns_no_question_still_reaches_the_panel() -> None:
    """Most of a meeting (FR-5.7), and the case the transcript exists for.

    Before it, the only thing capture could put on the panel was a nudge — so
    a quiet gate and a dead microphone produced the same screen.
    """

    client = _app_hearing(["The haulier phones the gate office."])
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=1)

    heard = _utterances(client, meeting_id)
    assert [u["text"] for u in heard] == ["The haulier phones the gate office."]
    assert heard[0]["speaker"] is None


def test_every_window_lands_in_the_order_it_was_spoken() -> None:
    """A transcript out of order misattributes an answer to the wrong question."""

    said = [
        "So how are arrivals booked in today?",
        "The haulier phones the gate office.",
        "And someone writes it on the whiteboard.",
    ]
    client = _app_hearing(said)
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=3)

    heard = _utterances(client, meeting_id)
    assert [u["text"] for u in heard] == said
    assert [u["seq"] for u in heard] == [0, 1, 2]


def test_a_silent_window_puts_no_empty_line_on_the_panel() -> None:
    """Most windows of most meetings are silence.

    A recogniser answers `''` for a window with no speech in it, and a
    transcript that showed one blank row per four seconds of quiet would bury
    the meeting in its own silence.
    """

    client = _app_hearing(["", "", "Three fifty a day."])
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=3)

    assert [u["text"] for u in _utterances(client, meeting_id)] == ["Three fifty a day."]


def _lane(client: TestClient, meeting_id: str) -> dict:
    """The stream's opening frame, which is always `lane`."""

    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        name: str | None = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: ") and name == "lane":
                return json.loads(line.removeprefix("data: "))
            elif line.startswith(":"):
                break
    raise AssertionError("the stream carried no lane frame")


def test_the_panel_is_told_when_nothing_will_transcribe() -> None:
    """A silent room and an unbought recogniser must not look the same.

    This did not matter while a nudge was the only thing capture could put on
    the panel — no nudges reads as a quiet meeting either way. It matters now
    there is a transcript region, because "Nothing heard yet." is what an
    operator sees for the whole meeting when the live lane has no credential,
    and it is indistinguishable from a room nobody is talking in and from a
    microphone that has stopped.

    This project has lost an evening to exactly that: "a live panel that sat
    at its resting state because a credential check nobody could see said no."
    `feed_live_lane` already documents the answer as the panel's to give —
    "the panel says as much through its own lane frame" — and the lane frame
    only ever carried the *model's* reachability, which is a different
    question with a different remedy.
    """

    client = TestClient(build_app(Backend()))
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription"] is False


def test_the_panel_is_told_when_the_room_will_be_transcribed() -> None:
    """And the other way, or the notice would be permanent furniture."""

    client = _app_hearing(["anything at all"])
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription"] is True


def test_what_the_panel_is_told_is_what_the_gate_decides() -> None:
    """One question, asked in one place.

    The gate and the recogniser once asked "is there a credential?" of two
    different places and disagreed, and an operator who had entered their key
    got silence with no error. A report that could drift from the gate the
    same way would be that bug again, wearing a label.
    """

    said = ["Three hundred and fifty a day."]
    client = _app_hearing(said)
    meeting_id = _meeting(client)

    reported = _lane(client, meeting_id)["live_transcription"]
    _capture(client, meeting_id, windows=1)
    actually_transcribed = [u["text"] for u in _utterances(client, meeting_id)] == said

    assert reported is actually_transcribed


def test_the_panel_is_not_told_it_is_transcribing_before_capture_starts() -> None:
    """A credential is not a microphone.

    `live_transcription` answers "could anything be transcribed" — is there a
    speech credential. The panel rendered that as a pulsing "Transcribing",
    which asserts the room *is* being written down, on a screen an operator
    opens before pressing Capture. Two different questions were collapsed into
    one label, and the label claimed the stronger of them.

    The evidence for the second question already exists: audio arriving is the
    only thing that separates a meeting being recorded from one opened and
    walked away from, which is exactly what `GET /api/sessions/live` reports
    from. This puts the same reading on the panel's own frame.
    """

    client = _app_hearing(["anything at all"])
    meeting_id = _meeting(client)

    lane = _lane(client, meeting_id)
    assert lane["live_transcription"] is True, "a recogniser is configured"
    assert lane["receiving_audio"] is False, "but nothing has been captured yet"


def test_the_panel_is_told_once_audio_is_arriving() -> None:
    """And the other way, or the operator could never tell it started."""

    client = _app_hearing(["Three fifty a day."])
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=1)

    assert _lane(client, meeting_id)["receiving_audio"] is True


def test_the_lane_frame_is_recomputed_rather_than_captured_once() -> None:
    """What the re-send depends on, asserted where it can be.

    A panel opens before the meeting does — that is the ordinary order — so
    the first lane frame always says no audio. The stream therefore re-sends it
    when it changes, exactly as it re-sends coverage, and for the same reason:
    the compile meter was read once at mount and showed thirteen per cent for
    five minutes of a compile that had finished.

    The interleaved case — one connection, capture starting while it is open —
    cannot be driven here: `TestClient` serialises requests, so a POST queues
    behind the very response it is meant to change. What is asserted instead is
    the property that re-sending rests on: the frame is computed per read, not
    captured when the generator was created. A frame built once would answer
    the same on a second connection too, and this fails if it does.
    """

    client = _app_hearing(["Three fifty a day."])
    meeting_id = _meeting(client)

    before = _lane(client, meeting_id)["receiving_audio"]
    _capture(client, meeting_id, windows=1)
    after = _lane(client, meeting_id)["receiving_audio"]

    assert (before, after) == (False, True)


def test_the_clock_counts_the_recording_not_the_meeting() -> None:
    """When this run of capture began, for the panel's clock.

    Not the session's `started_at`: a session is opened and never ended, so it
    keeps counting through a meeting nobody is recording. A clock that runs
    while the microphone is off is the same lie as a "Transcribing" label with
    no audio behind it, told in numbers.
    """

    client = _app_hearing(["Three fifty a day."])
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["capturing_since"] is None, "nothing captured yet"

    _capture(client, meeting_id, windows=1)
    started = _lane(client, meeting_id)["capturing_since"]

    assert isinstance(started, int)
    # Milliseconds since the epoch, matching every other instant on this
    # stream — the panel puts them on one timeline and cannot do that across
    # two formats.
    assert started > 1_600_000_000_000


def test_a_run_of_capture_keeps_its_own_start() -> None:
    """Chunk after chunk is one run, not a new one each time.

    A clock that reset on every four-second window would read zero for the
    whole meeting, which is the failure that looks most like working.
    """

    client = _app_hearing(["One.", "Two.", "Three."])
    meeting_id = _meeting(client)

    _capture(client, meeting_id, windows=1)
    first = _lane(client, meeting_id)["capturing_since"]
    _capture(client, meeting_id, windows=2)

    assert _lane(client, meeting_id)["capturing_since"] == first


def test_the_panel_is_told_why_every_line_is_unattributed() -> None:
    """A whole transcript reading "Unattributed", explained.

    Verification is two-way — one window against one enrolled print, answering
    the operator, not the operator, or cannot tell — and with nothing enrolled
    every window is the third. `identify_speaker` returning `None` is the
    honest answer and the gate behaves exactly as it does with no verification
    at all. What was wrong was the screen: every row said "Unattributed" with
    nothing anywhere saying why or what would change it, which reads as a
    transcript that is broken rather than one being careful.
    """

    client = TestClient(build_app(Backend()))
    meeting_id = _meeting(client)

    reason = _lane(client, meeting_id)["speaker_attribution_reason"]

    assert reason is not None
    assert "voiceprint" in reason
    # The remedy has to be nameable. "Attribution unavailable" is a fact an
    # operator can do nothing with.
    assert "enrolled" in reason
