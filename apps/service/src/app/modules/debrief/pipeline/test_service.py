"""Tests for the full-diarization orchestrator (PRD FR-7.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.pipeline.models import (
    UNKNOWN_SPEAKER_TAG,
    DiarizationOutput,
    DiarizationStatus,
    SessionDiarization,
    SpeakerTurn,
    TranscriptSpan,
)
from app.modules.debrief.pipeline.service import run_diarization

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_spans() -> list[TranscriptSpan]:
    return [
        TranscriptSpan(start_seconds=0.0, end_seconds=1.0, text="hello there"),
        TranscriptSpan(start_seconds=1.0, end_seconds=2.0, text="how are you"),
    ]


def make_diarize(turns: list[SpeakerTurn], *, engine: str = "diarizer-a", fail: bool = False):
    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        if fail:
            raise RuntimeError("diarization vendor timed out")
        return DiarizationOutput(engine=engine, turns=turns)

    return diarize


def test_a_successful_run_persists_a_speaker_tagged_utterance_per_span():
    saved: list[SessionDiarization] = []

    async def save(record: SessionDiarization) -> None:
        saved.append(record)

    turns = [
        SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="alice"),
        SpeakerTurn(start_seconds=1.0, end_seconds=2.0, speaker_tag="bob"),
    ]

    result = asyncio.run(
        run_diarization(
            "session-1",
            "recordings/session-1.wav",
            make_spans(),
            "diarizer-a",
            make_diarize(turns),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == DiarizationStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "diarizer-a"
    assert len(result.utterances) == 2
    assert [u.speaker_tag for u in result.utterances] == ["alice", "bob"]
    assert all(u.session_id == "session-1" for u in result.utterances)
    assert all(u.speaker_tag for u in result.utterances)
    assert saved == [result]


def test_every_utterance_gets_a_unique_id():
    async def save(record: SessionDiarization) -> None:
        pass

    turns = [SpeakerTurn(start_seconds=0.0, end_seconds=2.0, speaker_tag="alice")]

    result = asyncio.run(
        run_diarization(
            "session-1", "recordings/session-1.wav", make_spans(), "diarizer-a", make_diarize(turns), save
        )
    )

    ids = [u.utterance_id for u in result.utterances]
    assert len(ids) == len(set(ids))
    assert all(ids)


def test_a_span_the_diarization_output_does_not_cover_is_tagged_unknown_not_null():
    async def save(record: SessionDiarization) -> None:
        pass

    result = asyncio.run(
        run_diarization(
            "session-1", "recordings/session-1.wav", make_spans(), "diarizer-a", make_diarize([]), save
        )
    )

    assert all(u.speaker_tag == UNKNOWN_SPEAKER_TAG for u in result.utterances)


def test_a_failed_diarization_run_persists_a_failed_record_with_no_utterances():
    saved: list[SessionDiarization] = []

    async def save(record: SessionDiarization) -> None:
        saved.append(record)

    result = asyncio.run(
        run_diarization(
            "session-1",
            "recordings/session-1.wav",
            make_spans(),
            "diarizer-a",
            make_diarize([], fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == DiarizationStatus.FAILED
    assert result.engine == "diarizer-a"
    assert result.utterances == []
    assert result.error == "diarization vendor timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_requested_at_is_deterministic_when_supplied():
    async def save(record: SessionDiarization) -> None:
        pass

    turns = [SpeakerTurn(start_seconds=0.0, end_seconds=2.0, speaker_tag="alice")]

    result = asyncio.run(
        run_diarization(
            "session-1",
            "recordings/session-1.wav",
            make_spans(),
            "diarizer-a",
            make_diarize(turns),
            save,
            requested_at=FIXED,
        )
    )

    assert result.requested_at == FIXED
    assert result.completed_at >= FIXED


def test_utterance_ids_can_be_supplied_deterministically():
    async def save(record: SessionDiarization) -> None:
        pass

    turns = [SpeakerTurn(start_seconds=0.0, end_seconds=2.0, speaker_tag="alice")]
    counter = iter(["utt-1", "utt-2"])

    result = asyncio.run(
        run_diarization(
            "session-1",
            "recordings/session-1.wav",
            make_spans(),
            "diarizer-a",
            make_diarize(turns),
            save,
            make_utterance_id=lambda: next(counter),
        )
    )

    assert [u.utterance_id for u in result.utterances] == ["utt-1", "utt-2"]


def test_no_spans_persists_a_complete_record_with_no_utterances():
    async def save(record: SessionDiarization) -> None:
        pass

    result = asyncio.run(
        run_diarization("session-1", "recordings/session-1.wav", [], "diarizer-a", make_diarize([]), save)
    )

    assert result.status == DiarizationStatus.COMPLETE
    assert result.utterances == []
