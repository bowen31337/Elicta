"""The live lane's tap on the chunk upload.

Recording is the load-bearing thing on this route. The live lane is an extra
that reads the same bytes on their way past, and the ordering of those two
facts is the whole of what is asserted here: a recogniser that is refusing,
throttled or misconfigured must cost the meeting its nudges and nothing else.
Losing a recording because a nudge could not be raised would be a trade nobody
would make on purpose.
"""

from __future__ import annotations

import base64
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

_hold = importlib.import_module("app.modules.asr-record.audio_hold")

PCM = base64.b64encode(b"\x01\x02" * 16).decode()


async def _retained(session_id: str, audio_ref: str) -> None:
    return None


def _client(on_chunk) -> TestClient:
    app = FastAPI()
    app.include_router(_hold.build_audio_chunk_router({}, _retained, None, on_chunk=on_chunk))
    return TestClient(app)


def test_the_bytes_are_offered_to_the_live_lane_as_they_arrive() -> None:
    heard: list[tuple[str, bytes]] = []

    async def on_chunk(session_id: str, pcm: bytes) -> None:
        heard.append((session_id, pcm))

    accepted = _client(on_chunk).post(
        "/api/sessions/meeting-1/audio-chunk", json={"sequence": 0, "pcm": PCM}
    )

    assert accepted.status_code == 202, accepted.text
    assert heard == [("meeting-1", b"\x01\x02" * 16)]


def test_a_failing_live_lane_does_not_cost_the_recording_a_chunk() -> None:
    """The recording outlives the meeting; a nudge is worth thirty seconds."""

    async def on_chunk(session_id: str, pcm: bytes) -> None:
        raise RuntimeError("the recogniser is refusing this credential")

    accepted = _client(on_chunk).post(
        "/api/sessions/meeting-1/audio-chunk", json={"sequence": 0, "pcm": PCM}
    )

    assert accepted.status_code == 202, accepted.text


def test_a_chunk_the_hold_refused_is_not_offered_to_the_live_lane() -> None:
    """Out of order is a real gap in the audio, not something to transcribe."""

    heard: list[str] = []

    async def on_chunk(session_id: str, pcm: bytes) -> None:
        heard.append(session_id)

    client = _client(on_chunk)
    client.post("/api/sessions/meeting-1/audio-chunk", json={"sequence": 0, "pcm": PCM})
    refused = client.post("/api/sessions/meeting-1/audio-chunk", json={"sequence": 7, "pcm": PCM})

    assert refused.status_code == 409, refused.text
    assert heard == ["meeting-1"], "the refused chunk reached the live lane anyway"
