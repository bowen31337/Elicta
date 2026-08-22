"""The service-tier hold the record path transcribes from (spec §5.3).

`audio_ref` has never had a value: the schema calls it "a storage key or URI"
from a recording store that does not exist. It names this hold now.
"""

from __future__ import annotations

import base64
import importlib

import pytest

audio_hold = importlib.import_module("app.modules.asr-record.audio_hold")


def _pcm(byte: int, count: int) -> str:
    return base64.b64encode(bytes([byte]) * count).decode()


def test_chunks_append_in_order() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}

    first = audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))
    second = audio_hold.append_chunk(held, "meeting-1", sequence=1, pcm=_pcm(2, 6))

    assert first.next_sequence == 1
    assert second.received_bytes == 10
    assert bytes(held["meeting-1"].buffer) == bytes([1] * 4 + [2] * 6)


def test_a_gap_is_refused_rather_than_concatenated_across() -> None:
    """Silently joining the two sides of a dropped chunk makes a transcript
    with a seam nobody can see, which is worse than a refusal to retry."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))

    with pytest.raises(audio_hold.ChunkOutOfOrder) as raised:
        audio_hold.append_chunk(held, "meeting-1", sequence=2, pcm=_pcm(3, 4))

    assert "expected 1" in str(raised.value)
    assert bytes(held["meeting-1"].buffer) == bytes([1] * 4)


def test_a_resent_chunk_is_refused_too() -> None:
    """Retrying an acknowledged chunk would duplicate audio, not repair it."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))

    with pytest.raises(audio_hold.ChunkOutOfOrder):
        audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))


def test_sessions_are_held_separately() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}

    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 2))
    audio_hold.append_chunk(held, "meeting-2", sequence=0, pcm=_pcm(9, 2))

    assert bytes(held["meeting-1"].buffer) == bytes([1, 1])
    assert bytes(held["meeting-2"].buffer) == bytes([9, 9])


def test_the_audio_ref_names_the_hold() -> None:
    assert audio_hold.audio_ref_for("meeting-1") == "session:meeting-1"


def test_the_endpoint_accepts_a_chunk_and_refuses_a_gap() -> None:
    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    client = TestClient(build_app(Backend()))

    accepted = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {"received_bytes": 4, "next_sequence": 1}

    gap = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 5, "pcm": _pcm(1, 4)},
    )
    assert gap.status_code == 409, gap.text
    assert "expected 1" in gap.json()["detail"]


def test_the_first_chunk_marks_the_audio_retained() -> None:
    """So the existing NFR-2.4 destruction gate sees this session at all."""

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    backend = Backend()
    client = TestClient(build_app(backend))
    client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )

    assert backend.retained_audio["meeting-1"] == "session:meeting-1"


def test_a_chunk_is_refused_once_the_audio_has_been_destroyed() -> None:
    """NFR-2.4's destruction record has to stay true after it is written.

    The hold is a dict keyed by session, so a chunk with `sequence: 0` for a
    finished session simply recreated it — and nothing destroyed it a second
    time, because `destroy_if_ready` is only re-entered when a gating stage
    finishes and both had already finished. The service was left holding
    audio for a session whose own destruction event says it holds none.
    """

    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app
    from app.modules.debrief.pipeline.models import (
        AudioDestructionEvent,
        AudioDestructionStatus,
    )

    backend = Backend()
    client = TestClient(build_app(backend))

    client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )

    now = datetime.now(UTC)
    backend.audio_destruction_events.append(
        AudioDestructionEvent(
            session_id="meeting-1",
            audio_ref="session:meeting-1",
            status=AudioDestructionStatus.COMPLETE,
            requested_at=now,
            completed_at=now,
        )
    )
    backend.retained_audio.pop("meeting-1", None)
    backend.session_audio.pop("meeting-1", None)

    late = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(7, 4)},
    )

    assert late.status_code == 410, late.text
    assert "meeting-1" not in backend.session_audio, "destroyed audio came back"
    assert "meeting-1" not in backend.retained_audio, (
        "the session was recorded as holding audio again, with nothing left to destroy it"
    )


def test_another_session_is_unaffected_by_a_destroyed_one() -> None:
    """The refusal is per session, not a switch that closes the endpoint."""

    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app
    from app.modules.debrief.pipeline.models import (
        AudioDestructionEvent,
        AudioDestructionStatus,
    )

    backend = Backend()
    client = TestClient(build_app(backend))

    now = datetime.now(UTC)
    backend.audio_destruction_events.append(
        AudioDestructionEvent(
            session_id="meeting-1",
            audio_ref="session:meeting-1",
            status=AudioDestructionStatus.COMPLETE,
            requested_at=now,
            completed_at=now,
        )
    )

    accepted = client.post(
        "/api/sessions/meeting-2/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )

    assert accepted.status_code == 202, accepted.text
