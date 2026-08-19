"""Tests for the transcript-cleaning orchestrator (PRD FR-7.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.pipeline.cleaning import run_transcript_cleaning
from app.modules.debrief.pipeline.models import (
    SessionTranscriptCleaning,
    TranscriptCleaningStatus,
    Utterance,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_utterances() -> list[Utterance]:
    return [
        Utterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            text="um so like we need the, uh, thing by friday",
            speaker_tag="alice",
        ),
        Utterance(
            utterance_id="utt-2",
            session_id="session-1",
            start_seconds=1.0,
            end_seconds=2.0,
            text="yeah that works for me",
            speaker_tag="bob",
        ),
    ]


def make_clean(cleaned_texts: list[str], *, fail: bool = False):
    async def clean(session_id: str, utterances: list[Utterance]) -> list[str]:
        if fail:
            raise RuntimeError("cleaning vendor timed out")
        return cleaned_texts

    return clean


def test_a_successful_run_persists_cleaned_text_alongside_the_verbatim_original():
    saved: list[SessionTranscriptCleaning] = []

    async def save(record: SessionTranscriptCleaning) -> None:
        saved.append(record)

    utterances = make_utterances()
    cleaned_texts = ["We need the thing by Friday.", "Yeah, that works for me."]

    result = asyncio.run(
        run_transcript_cleaning(
            "session-1",
            utterances,
            "cleaner-a",
            make_clean(cleaned_texts),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == TranscriptCleaningStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "cleaner-a"
    assert len(result.utterances) == 2
    assert [u.cleaned_text for u in result.utterances] == cleaned_texts
    assert [u.verbatim_text for u in result.utterances] == [u.text for u in utterances]
    assert [u.utterance_id for u in result.utterances] == ["utt-1", "utt-2"]
    assert [u.speaker_tag for u in result.utterances] == ["alice", "bob"]
    assert all(u.session_id == "session-1" for u in result.utterances)
    assert saved == [result]


def test_verbatim_text_is_untouched_even_when_cleaned_text_differs_a_lot():
    async def save(record: SessionTranscriptCleaning) -> None:
        pass

    utterances = make_utterances()

    result = asyncio.run(
        run_transcript_cleaning(
            "session-1",
            utterances,
            "cleaner-a",
            make_clean(["We need the thing by Friday.", "Yeah, that works for me."]),
            save,
        )
    )

    assert result.utterances[0].verbatim_text == "um so like we need the, uh, thing by friday"
    assert result.utterances[0].cleaned_text == "We need the thing by Friday."


def test_a_failed_cleaning_run_persists_a_failed_record_with_no_utterances():
    saved: list[SessionTranscriptCleaning] = []

    async def save(record: SessionTranscriptCleaning) -> None:
        saved.append(record)

    result = asyncio.run(
        run_transcript_cleaning(
            "session-1",
            make_utterances(),
            "cleaner-a",
            make_clean([], fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == TranscriptCleaningStatus.FAILED
    assert result.engine == "cleaner-a"
    assert result.utterances == []
    assert result.error == "cleaning vendor timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_a_mismatched_cleaned_text_count_persists_a_failed_record_instead_of_raising():
    saved: list[SessionTranscriptCleaning] = []

    async def save(record: SessionTranscriptCleaning) -> None:
        saved.append(record)

    result = asyncio.run(
        run_transcript_cleaning(
            "session-1",
            make_utterances(),
            "cleaner-a",
            make_clean(["only one cleaned utterance"]),
            save,
        )
    )

    assert result.status == TranscriptCleaningStatus.FAILED
    assert result.utterances == []
    assert result.error is not None
    assert saved == [result]


def test_no_utterances_persists_a_complete_record_with_no_utterances():
    async def save(record: SessionTranscriptCleaning) -> None:
        pass

    result = asyncio.run(
        run_transcript_cleaning("session-1", [], "cleaner-a", make_clean([]), save)
    )

    assert result.status == TranscriptCleaningStatus.COMPLETE
    assert result.utterances == []


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    async def save(record: SessionTranscriptCleaning) -> None:
        pass

    result = asyncio.run(
        run_transcript_cleaning(
            "session-1",
            make_utterances(),
            "cleaner-a",
            make_clean(["clean one", "clean two"]),
            save,
        )
    )

    assert result.completed_at >= result.requested_at
