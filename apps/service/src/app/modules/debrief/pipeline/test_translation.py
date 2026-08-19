"""Tests for the transcript-translation orchestrator (PRD FR-8.7a)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.pipeline.models import (
    CleanedUtterance,
    SessionTranscriptTranslation,
    TranscriptTranslationStatus,
    TranslationOutcome,
)
from app.modules.debrief.pipeline.translation import (
    normalize_translated_text,
    run_transcript_translation,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_utterances() -> list[CleanedUtterance]:
    return [
        CleanedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="um we need the thing by friday",
            cleaned_text="We need the thing by Friday.",
        ),
        CleanedUtterance(
            utterance_id="utt-2",
            session_id="session-1",
            start_seconds=1.0,
            end_seconds=2.0,
            speaker_tag="bob",
            verbatim_text="necesitamos esto para el viernes",
            cleaned_text="Necesitamos esto para el viernes.",
        ),
    ]


def make_translate(outcomes: list[TranslationOutcome], *, fail: bool = False):
    async def translate(
        session_id: str, utterances: list[CleanedUtterance], document_language: str
    ) -> list[TranslationOutcome]:
        if fail:
            raise RuntimeError("translation vendor timed out")
        return outcomes

    return translate


def test_a_successful_run_tags_language_and_attaches_a_translation_for_a_cross_language_utterance():
    saved: list[SessionTranscriptTranslation] = []

    async def save(record: SessionTranscriptTranslation) -> None:
        saved.append(record)

    utterances = make_utterances()
    outcomes = [
        TranslationOutcome(original_language="en"),
        TranslationOutcome(original_language="es", translated_text="We need this by Friday."),
    ]

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            utterances,
            "en",
            "translator-a",
            make_translate(outcomes),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == TranscriptTranslationStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "translator-a"
    assert result.document_language == "en"
    assert [u.original_language for u in result.utterances] == ["en", "es"]
    assert [u.translated_text for u in result.utterances] == [None, "We need this by Friday."]
    assert [u.verbatim_text for u in result.utterances] == [u.verbatim_text for u in utterances]
    assert [u.utterance_id for u in result.utterances] == ["utt-1", "utt-2"]
    assert saved == [result]


def test_verbatim_original_language_text_is_untouched_by_translation():
    async def save(record: SessionTranscriptTranslation) -> None:
        pass

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            make_utterances(),
            "en",
            "translator-a",
            make_translate(
                [
                    TranslationOutcome(original_language="en"),
                    TranslationOutcome(original_language="es", translated_text="We need this by Friday."),
                ]
            ),
            save,
        )
    )

    assert result.utterances[1].verbatim_text == "necesitamos esto para el viernes"
    assert result.utterances[1].translated_text == "We need this by Friday."


def test_a_same_language_translation_is_normalized_away_even_if_the_engine_returns_one():
    async def save(record: SessionTranscriptTranslation) -> None:
        pass

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            make_utterances()[:1],
            "en",
            "translator-a",
            make_translate([TranslationOutcome(original_language="en-US", translated_text="We need the thing.")]),
            save,
        )
    )

    assert result.utterances[0].original_language == "en-US"
    assert result.utterances[0].translated_text is None


def test_a_failed_translation_run_persists_a_failed_record_with_no_utterances():
    saved: list[SessionTranscriptTranslation] = []

    async def save(record: SessionTranscriptTranslation) -> None:
        saved.append(record)

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            make_utterances(),
            "en",
            "translator-a",
            make_translate([], fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == TranscriptTranslationStatus.FAILED
    assert result.engine == "translator-a"
    assert result.utterances == []
    assert result.error == "translation vendor timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_a_mismatched_outcome_count_persists_a_failed_record_instead_of_raising():
    saved: list[SessionTranscriptTranslation] = []

    async def save(record: SessionTranscriptTranslation) -> None:
        saved.append(record)

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            make_utterances(),
            "en",
            "translator-a",
            make_translate([TranslationOutcome(original_language="en")]),
            save,
        )
    )

    assert result.status == TranscriptTranslationStatus.FAILED
    assert result.utterances == []
    assert result.error is not None
    assert saved == [result]


def test_no_utterances_persists_a_complete_record_with_no_utterances():
    async def save(record: SessionTranscriptTranslation) -> None:
        pass

    result = asyncio.run(
        run_transcript_translation("session-1", [], "en", "translator-a", make_translate([]), save)
    )

    assert result.status == TranscriptTranslationStatus.COMPLETE
    assert result.utterances == []


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    async def save(record: SessionTranscriptTranslation) -> None:
        pass

    result = asyncio.run(
        run_transcript_translation(
            "session-1",
            make_utterances(),
            "en",
            "translator-a",
            make_translate(
                [TranslationOutcome(original_language="en"), TranslationOutcome(original_language="en")]
            ),
            save,
        )
    )

    assert result.completed_at >= result.requested_at


def test_normalize_translated_text_passes_through_a_genuinely_cross_language_translation():
    assert normalize_translated_text("es", "en", "We need this by Friday.") == "We need this by Friday."


def test_normalize_translated_text_drops_a_same_language_translation():
    assert normalize_translated_text("en", "en", "We need the thing.") is None


def test_normalize_translated_text_compares_bcp47_primary_subtags():
    assert normalize_translated_text("en-US", "en-GB", "We need the thing.") is None
    assert normalize_translated_text("zh-Hans", "en", "We need this.") == "We need this."
