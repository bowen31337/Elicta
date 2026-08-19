"""Tests for destroying a session's raw retained audio once processing completes (PRD NFR-2.4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.pipeline.models import (
    AudioDestructionEvent,
    AudioDestructionStatus,
    DiarizationStatus,
    SessionDiarization,
)
from app.modules.debrief.pipeline.retention import (
    destroy_retained_audio,
    is_ready_for_audio_destruction,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_diarization(status: DiarizationStatus) -> SessionDiarization:
    return SessionDiarization(
        session_id="session-1",
        status=status,
        engine="diarizer-a",
        utterances=[],
        requested_at=FIXED,
        completed_at=FIXED,
    )


def test_not_ready_when_transcription_has_not_finished():
    diarization = make_diarization(DiarizationStatus.COMPLETE)

    assert is_ready_for_audio_destruction(diarization, transcription_terminal=False) is False


def test_ready_once_both_transcription_and_diarization_completed():
    diarization = make_diarization(DiarizationStatus.COMPLETE)

    assert is_ready_for_audio_destruction(diarization, transcription_terminal=True) is True


def test_ready_even_when_diarization_failed_since_failure_is_still_terminal():
    diarization = make_diarization(DiarizationStatus.FAILED)

    assert is_ready_for_audio_destruction(diarization, transcription_terminal=True) is True


def test_a_successful_deletion_emits_a_complete_destruction_event():
    emitted: list[AudioDestructionEvent] = []
    deleted: list[tuple[str, str]] = []

    async def delete_audio(session_id: str, audio_ref: str) -> None:
        deleted.append((session_id, audio_ref))

    async def emit(event: AudioDestructionEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        destroy_retained_audio(
            "session-1",
            "recordings/session-1.wav",
            delete_audio,
            emit,
            requested_at=FIXED,
        )
    )

    assert result.status == AudioDestructionStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.audio_ref == "recordings/session-1.wav"
    assert result.error is None
    assert deleted == [("session-1", "recordings/session-1.wav")]
    assert emitted == [result]


def test_a_failed_deletion_emits_a_failed_destruction_event_not_an_exception():
    emitted: list[AudioDestructionEvent] = []

    async def delete_audio(session_id: str, audio_ref: str) -> None:
        raise RuntimeError("blob store unavailable")

    async def emit(event: AudioDestructionEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        destroy_retained_audio(
            "session-1",
            "recordings/session-1.wav",
            delete_audio,
            emit,
            requested_at=FIXED,
        )
    )

    assert result.status == AudioDestructionStatus.FAILED
    assert result.error == "blob store unavailable"
    assert emitted == [result]


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    async def delete_audio(session_id: str, audio_ref: str) -> None:
        pass

    async def emit(event: AudioDestructionEvent) -> None:
        pass

    result = asyncio.run(
        destroy_retained_audio("session-1", "recordings/session-1.wav", delete_audio, emit)
    )

    assert result.completed_at >= result.requested_at
