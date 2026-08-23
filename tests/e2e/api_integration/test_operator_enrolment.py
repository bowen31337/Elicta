"""Enrolling a voice, and the meeting that follows knowing whose it is.

Two seams that were empty in opposite directions. The capture screen offered
an Enrol button that did nothing, because no route existed behind it; and the
trigger gate carried a `speaker` field that nothing ever set, so a nudge fired
on the operator's own sentence exactly as readily as on the client's.

Driven through the production composition root, so what is asserted here is
the assembly that ships.
"""

from __future__ import annotations

import base64
import math
import random

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.voiceprint.embedding import SAMPLE_RATE

# Two vocal tracts far enough apart to be different people. Synthesised
# because a fixture of real speech cannot live in this repo, and because
# nothing here is testing the recogniser's accuracy — only that a print made
# by one route is the one the live lane compares against.
OPERATOR_TRACT = (730.0, 1090.0, 2440.0)
CLIENT_TRACT = (390.0, 1990.0, 2550.0)


def speech(tract: tuple[float, float, float], *, f0: float = 120.0, seconds: float = 6.0) -> bytes:
    """A crude vowel, with real gaps between syllables."""

    rng = random.Random(11)
    out = bytearray()
    harmonics = int(SAMPLE_RATE / 2 / f0)
    for n in range(int(SAMPLE_RATE * seconds)):
        t = n / SAMPLE_RATE
        envelope = max(0.0, math.sin(2 * math.pi * 4.0 * t)) ** 2
        value = 0.0
        if envelope > 0.01:
            for harmonic in range(1, harmonics):
                frequency = f0 * harmonic
                shaping = sum(1.0 / (1.0 + ((frequency - f) / 90.0) ** 2) for f in tract)
                value += shaping * math.sin(2 * math.pi * frequency * t) / harmonic
        value = value * envelope / 8.0 + rng.uniform(-0.001, 0.001)
        sample = max(-32768, min(32767, int(value * 0.3 * 32767)))
        out += int(sample).to_bytes(2, "little", signed=True)
    return bytes(out)


def enrol(client: TestClient, audio: bytes) -> dict:
    response = client.post(
        "/api/operator/voiceprint",
        json={"pcm": base64.b64encode(audio).decode("ascii")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_operator_can_enrol_and_read_it_back(client: TestClient) -> None:
    assert client.get("/api/operator/voiceprint").json()["enrolled"] is False

    enrol(client, speech(OPERATOR_TRACT))

    status = client.get("/api/operator/voiceprint").json()
    assert status["enrolled"] is True
    assert status["usable"] is True
    assert status["sample_seconds"] == 6.0


def test_the_enrolment_survives_a_restart(settings_store) -> None:
    """The whole reason this has a table. Nothing rebuilds a voiceprint: the
    only thing that produces one is a person recording themselves."""

    backend = Backend()
    first = TestClient(build_app(backend, settings_store=settings_store))
    enrol(first, speech(OPERATOR_TRACT))

    # A second app over the same backend is what a restart looks like from
    # here — the collections are opened once and bound in, so this is the
    # boundary that lost the record path's transcripts before.
    second = TestClient(build_app(backend, settings_store=settings_store))

    assert second.get("/api/operator/voiceprint").json()["enrolled"] is True


def test_the_sample_is_never_readable_back_out_of_the_api(client: TestClient) -> None:
    """FR-1.7 and the settings surface's discipline together: the audio is not
    stored at all, and the print it became is not returned."""

    enrol(client, speech(OPERATOR_TRACT))

    body = client.get("/api/operator/voiceprint").json()

    # `embedding_model` is named on purpose — it is how the screen knows a
    # print has gone stale. What must not be here is the vector itself.
    assert "embedding" not in body
    assert body["embedding_model"] == "mfcc-stats-v1"
    assert "pcm" not in body


def test_un_enrolling_leaves_nothing_behind(client: TestClient) -> None:
    enrol(client, speech(OPERATOR_TRACT))

    assert client.delete("/api/operator/voiceprint").status_code == 204
    assert client.get("/api/operator/voiceprint").json()["enrolled"] is False


# --- the live lane ------------------------------------------------------


@pytest.fixture
def meeting(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Depot Co",
            "sector": "logistics",
            "commercial_context": "Warehouse rollout",
        },
    )
    assert engagement.status_code in (200, 201), engagement.text
    engagement_id = engagement.json()["engagement_id"]
    created = client.post(
        "/api/meetings", json={"engagement_id": engagement_id, "capture_mode": "monolingual"}
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["meeting_id"]


VAGUE = "We need the dashboard to be fast for quite a few users."


def test_a_clients_vague_sentence_still_reaches_the_gate(
    client: TestClient, meeting: str
) -> None:
    """The baseline this must not regress: with nobody tagged, nothing changes."""

    accepted = client.post(f"/api/meetings/{meeting}/live/utterance", json={"text": VAGUE})

    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["triggered"] is True


def test_the_same_sentence_from_the_operator_is_not_interrogated(
    client: TestClient, meeting: str
) -> None:
    """FR-1.6, and architecture section 3.5. A nudge asking the operator to
    interrogate their own sentence is never useful, and every one spent on it
    comes out of the rate limit the questions that matter share."""

    accepted = client.post(
        f"/api/meetings/{meeting}/live/utterance",
        json={"text": VAGUE, "speaker": "operator"},
    )

    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["triggered"] is False
    assert body["trigger_reason"] == "operator speech"
    assert body["surfaced"] is False


def test_an_unverifiable_speaker_is_treated_exactly_as_today(
    client: TestClient, meeting: str
) -> None:
    """`None` is what verification answers when nobody enrolled, when the print
    came from a retired embedder, and when the window held no speech. All three
    have to fall through to the gate, or enrolling would become the thing that
    decides whether the product works at all."""

    accepted = client.post(
        f"/api/meetings/{meeting}/live/utterance", json={"text": VAGUE, "speaker": None}
    )

    assert accepted.json()["triggered"] is True


def _nudges_from_one_window(
    settings_store, voice: tuple[float, float, float], *, enrolled: bool
) -> int:
    """Upload four seconds of one voice the way the capture screen does, and
    count what the panel was sent. An injected recogniser stands in for the
    vendor, so this spends no speech credential and still drives every join
    between the upload and the gate."""

    heard: list[str] = []

    async def recognise(session_id: str, window: bytes) -> str:
        heard.append(session_id)
        return VAGUE

    backend = Backend()
    client = TestClient(
        build_app(backend, settings_store=settings_store, live_recogniser=recognise)
    )

    if enrolled:
        enrol(client, speech(OPERATOR_TRACT))

    engagement_id = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Depot Co",
            "sector": "logistics",
            "commercial_context": "Warehouse rollout",
        },
    ).json()["engagement_id"]
    meeting_id = client.post(
        "/api/meetings", json={"engagement_id": engagement_id, "capture_mode": "monolingual"}
    ).json()["meeting_id"]

    posted = client.post(
        f"/api/sessions/{meeting_id}/audio-chunk",
        json={
            "sequence": 0,
            "pcm": base64.b64encode(speech(voice, f0=126.0, seconds=4.0)).decode("ascii"),
        },
    )
    assert posted.status_code in (200, 201, 202), posted.text
    # The lane ran at all. Without this every count below could be zero for
    # reasons that have nothing to do with who was speaking.
    assert heard == [meeting_id]

    return len([name for name, _ in backend.live_events.get(meeting_id, []) if name == "nudge"])


def test_uploaded_audio_is_verified_against_the_enrolled_print(settings_store) -> None:
    """The join, end to end, and the reason it is asserted as a contrast.

    "The operator's sentence raised no nudge" is true of a pipeline that raises
    no nudges at all, which is what this seam looked like for most of its life.
    So the same window is driven three ways, and only the middle one moves:
    with nobody enrolled the client is interrogated exactly as before, with an
    enrolment the client still is, and the operator's own vague sentence is
    the only thing that stops being.
    """

    assert _nudges_from_one_window(settings_store, CLIENT_TRACT, enrolled=False) == 1
    assert _nudges_from_one_window(settings_store, CLIENT_TRACT, enrolled=True) == 1
    assert _nudges_from_one_window(settings_store, OPERATOR_TRACT, enrolled=True) == 0
