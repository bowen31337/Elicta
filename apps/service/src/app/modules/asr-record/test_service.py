"""Tests for the record-path batch re-transcription orchestrator.

Loaded via `importlib.import_module` with the full dotted path rather than
`from .service import ...`: this package's directory (`asr-record`) is not a
valid Python identifier, and pytest's default test-collection import mode
cannot resolve a relative import inside such a directory (it works fine at
real runtime via `app.module_loader`, which uses the same
`importlib.import_module` mechanism this file uses).
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import pytest

_models = importlib.import_module("app.modules.asr-record.models")
_service = importlib.import_module("app.modules.asr-record.service")

BatchTranscriptionOutput = _models.BatchTranscriptionOutput
RecordPathTranscript = _models.RecordPathTranscript
TranscriptionStatus = _models.TranscriptionStatus
TranscriptSegment = _models.TranscriptSegment
run_record_path_transcription = _service.run_record_path_transcription


def make_output(
    text: str = "the full session transcript",
) -> BatchTranscriptionOutput:
    return BatchTranscriptionOutput(
        engine="highest-accuracy-engine",
        segments=[
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="the full"),
            TranscriptSegment(
                start_seconds=1.5, end_seconds=3.0, text="session transcript"
            ),
        ],
        text=text,
    )


def test_a_successful_run_persists_a_complete_transcript_for_the_full_session():
    saved: list[RecordPathTranscript] = []

    async def transcribe(session_id: str, audio_ref: str) -> BatchTranscriptionOutput:
        assert session_id == "session-1"
        assert audio_ref == "recordings/session-1.wav"
        return make_output()

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    result = asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", transcribe, save
        )
    )

    assert result.status == TranscriptionStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "highest-accuracy-engine"
    assert result.text == "the full session transcript"
    assert len(result.segments) == 2
    assert result.error is None
    assert saved == [result]


def test_requested_at_is_deterministic_when_supplied():
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def transcribe(session_id: str, audio_ref: str) -> BatchTranscriptionOutput:
        return make_output()

    async def save(transcript: RecordPathTranscript) -> None:
        pass

    result = asyncio.run(
        run_record_path_transcription(
            "session-1",
            "recordings/session-1.wav",
            transcribe,
            save,
            requested_at=fixed,
        )
    )

    assert result.requested_at == fixed
    assert result.completed_at >= fixed


def test_an_engine_failure_persists_a_failed_transcript_and_reraises():
    saved: list[RecordPathTranscript] = []

    async def transcribe(session_id: str, audio_ref: str) -> BatchTranscriptionOutput:
        raise RuntimeError("vendor engine timed out")

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    with pytest.raises(RuntimeError, match="vendor engine timed out"):
        asyncio.run(
            run_record_path_transcription(
                "session-1", "recordings/session-1.wav", transcribe, save
            )
        )

    assert len(saved) == 1
    assert saved[0].status == TranscriptionStatus.FAILED
    assert saved[0].session_id == "session-1"
    assert saved[0].error == "vendor engine timed out"
    assert saved[0].segments == []
