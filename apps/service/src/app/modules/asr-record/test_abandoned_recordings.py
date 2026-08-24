"""Recordings that were started and never stopped (NFR-2.4).

A recording is opened deliberately and closed by its audio being destroyed,
which happens when the record path finishes with it. Nothing finishes for a
recording nobody stopped: the browser was closed, the laptop was shut, the
operator walked away. That hold would sit in memory holding raw audio for as
long as the service ran, which is the one thing NFR-2.4 forbids.

The old permanent block prevented this by accident, since nothing could open a
second recording at all. Opening them on purpose means closing them on purpose.
"""

from __future__ import annotations

import base64
import importlib
from datetime import UTC, datetime, timedelta

audio_hold = importlib.import_module("app.modules.asr-record.audio_hold")

NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
IDLE = timedelta(minutes=10)


def _pcm(byte: int, count: int) -> str:
    return base64.b64encode(bytes([byte]) * count).decode()


def test_a_recording_still_being_fed_is_not_stale() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.open_recording(held, "meeting-1", now=NOW - timedelta(hours=3))
    audio_hold.append_chunk(
        held, "meeting-1", sequence=0, pcm=_pcm(1, 4), now=NOW - timedelta(seconds=5)
    )

    assert audio_hold.stale_sessions(held, older_than=IDLE, now=NOW) == []


def test_a_long_meeting_is_measured_from_its_last_chunk_not_its_start() -> None:
    """A three-hour workshop is a long recording, not an abandoned one."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.open_recording(held, "meeting-1", now=NOW - timedelta(hours=3))
    for sequence in range(3):
        audio_hold.append_chunk(
            held,
            "meeting-1",
            sequence=sequence,
            pcm=_pcm(1, 4),
            now=NOW - timedelta(minutes=1),
        )

    assert audio_hold.stale_sessions(held, older_than=IDLE, now=NOW) == []


def test_a_recording_nothing_has_fed_for_too_long_is_stale() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.open_recording(held, "meeting-1", now=NOW - timedelta(hours=2))
    audio_hold.append_chunk(
        held, "meeting-1", sequence=0, pcm=_pcm(1, 4), now=NOW - timedelta(minutes=41)
    )
    audio_hold.open_recording(held, "meeting-2", now=NOW - timedelta(seconds=30))

    assert audio_hold.stale_sessions(held, older_than=IDLE, now=NOW) == ["meeting-1"]


def test_a_recording_opened_and_never_fed_goes_stale_on_its_own() -> None:
    """Start pressed, microphone dead, tab closed. No chunk ever arrived."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.open_recording(held, "meeting-1", now=NOW - timedelta(minutes=11))

    assert audio_hold.stale_sessions(held, older_than=IDLE, now=NOW) == ["meeting-1"]


async def test_the_sweep_destroys_abandoned_audio_and_records_that_it_did() -> None:
    """The discard has to be observable, exactly as the ordinary one is."""

    from app.composition import Backend, _install_audio_lifecycle

    backend = Backend()
    audio_hold.open_recording(
        backend.session_audio, "meeting-1", now=NOW - timedelta(hours=1)
    )
    backend.retained_audio["meeting-1"] = "session:meeting-1"

    events = await _install_audio_lifecycle(backend).sweep_abandoned(
        older_than=IDLE, now=NOW
    )

    assert [event.session_id for event in events] == ["meeting-1"]
    assert events[0].status.value == "complete"
    assert "meeting-1" not in backend.session_audio, "the hold outlived its audio"
    assert "meeting-1" not in backend.retained_audio
    assert backend.audio_destruction_events["meeting-1"] == events, (
        "audio was discarded with nothing recording that it had been"
    )


async def test_the_sweep_closes_a_recording_that_never_took_any_audio() -> None:
    """No audio was retained, so there is nothing to record destroying.

    A destruction event here would assert that audio existed and was
    discarded. None ever did, and NFR-2.4's record is worth only as much as
    its literal truth.
    """

    from app.composition import Backend, _install_audio_lifecycle

    backend = Backend()
    audio_hold.open_recording(
        backend.session_audio, "meeting-1", now=NOW - timedelta(hours=1)
    )

    events = await _install_audio_lifecycle(backend).sweep_abandoned(
        older_than=IDLE, now=NOW
    )

    assert events == []
    assert "meeting-1" not in backend.session_audio, "the hold was left open for ever"
    assert backend.audio_destruction_events == {}


async def test_the_sweep_leaves_a_live_recording_alone() -> None:
    from app.composition import Backend, _install_audio_lifecycle

    backend = Backend()
    audio_hold.open_recording(backend.session_audio, "meeting-1", now=NOW)
    backend.retained_audio["meeting-1"] = "session:meeting-1"

    events = await _install_audio_lifecycle(backend).sweep_abandoned(
        older_than=IDLE, now=NOW
    )

    assert events == []
    assert backend.retained_audio["meeting-1"] == "session:meeting-1"


# --- how long is too long -------------------------------------------------


def test_the_idle_window_defaults_to_ten_minutes(monkeypatch) -> None:
    monkeypatch.delenv(audio_hold.IDLE_SECONDS_ENV, raising=False)

    assert audio_hold.idle_seconds_from_env() == 600.0


def test_the_idle_window_can_be_tuned(monkeypatch) -> None:
    monkeypatch.setenv(audio_hold.IDLE_SECONDS_ENV, "90")

    assert audio_hold.idle_seconds_from_env() == 90.0


def test_a_malformed_idle_window_falls_back_rather_than_raising(monkeypatch) -> None:
    """Refusing to start the service over a tuning knob is the worse trade."""

    for bad in ("soon", "0", "-30", ""):
        monkeypatch.setenv(audio_hold.IDLE_SECONDS_ENV, bad)
        assert audio_hold.idle_seconds_from_env() == 600.0, bad
