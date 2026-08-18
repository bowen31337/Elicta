"""Tests for building the transcript artifact (PRD FR-8.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.debrief.artifacts.models import TranscriptArtifact, TranscriptArtifactStatus
from app.modules.debrief.artifacts.transcript import build_transcript_artifact
from app.modules.debrief.pipeline.models import SessionTranscriptTranslation, TranscriptTranslationStatus, TranslatedUtterance

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_utterance(
    utterance_id: str,
    start: float,
    end: float,
    *,
    speaker_tag: str = "alice",
    original_language: str = "en",
    translated_text: str | None = None,
) -> TranslatedUtterance:
    return TranslatedUtterance(
        utterance_id=utterance_id,
        session_id="session-1",
        start_seconds=start,
        end_seconds=end,
        speaker_tag=speaker_tag,
        verbatim_text=f"verbatim {utterance_id}",
        cleaned_text=f"cleaned {utterance_id}",
        original_language=original_language,
        translated_text=translated_text,
    )


def make_translation(
    *, utterances: list[TranslatedUtterance], status: TranscriptTranslationStatus, error: str | None = None,
    document_language: str = "en",
) -> SessionTranscriptTranslation:
    return SessionTranscriptTranslation(
        session_id="session-1",
        status=status,
        engine="translator-a",
        document_language=document_language,
        utterances=utterances,
        requested_at=FIXED,
        completed_at=FIXED,
        error=error,
    )


def test_a_complete_translation_run_produces_one_entry_per_utterance_in_order():
    saved: list[TranscriptArtifact] = []

    async def save(transcript: TranscriptArtifact) -> None:
        saved.append(transcript)

    translation = make_translation(
        utterances=[
            make_utterance("utt-1", 0.0, 1.0, speaker_tag="alice"),
            make_utterance("utt-2", 1.0, 2.5, speaker_tag="bob", original_language="fr", translated_text="hello"),
        ],
        status=TranscriptTranslationStatus.COMPLETE,
    )

    result = asyncio.run(build_transcript_artifact(translation, save, generated_at=FIXED))

    assert result.status == TranscriptArtifactStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.artifact_language == "en"
    assert result.generated_at == FIXED
    assert result.error is None
    assert len(result.entries) == 2

    first, second = result.entries
    assert first.utterance_id == "utt-1"
    assert first.speaker_tag == "alice"
    assert first.start_seconds == 0.0
    assert first.end_seconds == 1.0
    assert first.quoted_text == "verbatim utt-1"
    assert first.original_language == "en"
    assert first.translated_text is None

    assert second.utterance_id == "utt-2"
    assert second.speaker_tag == "bob"
    assert second.original_language == "fr"
    assert second.translated_text == "hello"

    assert saved == [result]


def test_a_non_complete_translation_run_persists_a_failed_transcript_with_no_entries():
    saved: list[TranscriptArtifact] = []

    async def save(transcript: TranscriptArtifact) -> None:
        saved.append(transcript)

    translation = make_translation(
        utterances=[], status=TranscriptTranslationStatus.FAILED, error="translation vendor timed out",
    )

    result = asyncio.run(build_transcript_artifact(translation, save, generated_at=FIXED))

    assert result.status == TranscriptArtifactStatus.FAILED
    assert result.entries == []
    assert result.error == "translation vendor timed out"
    assert result.artifact_language == "en"
    assert result.generated_at == FIXED
    assert saved == [result]


def test_a_failed_run_with_no_error_message_gets_a_default_one():
    async def save(transcript: TranscriptArtifact) -> None:
        pass

    translation = make_translation(utterances=[], status=TranscriptTranslationStatus.FAILED, error=None)

    result = asyncio.run(build_transcript_artifact(translation, save))

    assert result.status == TranscriptArtifactStatus.FAILED
    assert result.error == "transcript translation did not complete"


def test_no_utterances_persists_a_complete_transcript_with_no_entries():
    async def save(transcript: TranscriptArtifact) -> None:
        pass

    translation = make_translation(utterances=[], status=TranscriptTranslationStatus.COMPLETE)

    result = asyncio.run(build_transcript_artifact(translation, save))

    assert result.status == TranscriptArtifactStatus.COMPLETE
    assert result.entries == []
