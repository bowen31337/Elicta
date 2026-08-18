"""Tags each cleaned utterance's spoken language and attaches a translation, when needed (PRD FR-8.7a).

`run_transcript_translation` takes the translation pass itself as an
injected callable rather than importing a concrete MT vendor client
directly, mirroring `cleaning.py`'s `CleanTranscript` and
`classification.py`'s `ClassifyUtterances`: the vendor is still an open
decision, and no durable store exists yet in this codebase. Whoever wires
the app factory supplies the real implementation.

This stage runs after transcript cleaning and before section classification:
every later debrief stage — section classification, the BMAD analyst chain,
citations — reads `TranslatedUtterance.original_language`/`translated_text`
straight off the utterance rather than juggling a separate translation
lookup, so a citation across a language boundary can carry both the
original-language quote and its translation in one record (PRD FR-8.7a)
without those later stages having to know translation happened at all.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import (
    CleanedUtterance,
    SessionTranscriptTranslation,
    TranscriptTranslationStatus,
    TranslatedUtterance,
    TranslationOutcome,
)

TranslateTranscript = Callable[[str, list[CleanedUtterance], str], Awaitable[list[TranslationOutcome]]]
SaveSessionTranscriptTranslation = Callable[[SessionTranscriptTranslation], Awaitable[None]]


def _primary_subtag(language: str) -> str:
    """BCP-47 primary subtag, lowercased, so `"en-US"` and `"en"` compare equal.

    Duplicated locally rather than imported from anywhere else in this
    codebase — this pipeline package stays decoupled from other modules'
    (and other services') internals, the same convention `diarization.py`'s
    `TranscriptSpan` docstring documents for this package.
    """

    return language.split("-")[0].split("_")[0].strip().lower()


def normalize_translated_text(original_language: str, document_language: str, translated_text: str | None) -> str | None:
    """Return `translated_text` only when `original_language` actually differs from `document_language`.

    A translation engine that returns a "translation" for an utterance
    already in `document_language` (a same-language paraphrase, a vendor
    quirk) would otherwise make a same-language citation look cross-language
    to `resolve_citations` and the UI it feeds — PRD FR-8.7a only applies
    "where the meeting language differs from the artifact language". BCP-47
    tags are compared on primary subtag via `_primary_subtag`.
    """

    if _primary_subtag(original_language) == _primary_subtag(document_language):
        return None
    return translated_text


async def run_transcript_translation(
    session_id: str,
    utterances: list[CleanedUtterance],
    document_language: str,
    engine: str,
    translate: TranslateTranscript,
    save: SaveSessionTranscriptTranslation,
    *,
    requested_at: datetime | None = None,
) -> SessionTranscriptTranslation:
    """Tag every utterance's spoken language and attach its translation, then persist the run (PRD FR-8.7a).

    On success, every utterance in `utterances` becomes a `TranslatedUtterance`
    carrying the `original_language` `translate` returned for it and a
    `translated_text` normalized via `normalize_translated_text` (`None` for
    an utterance already in `document_language`), in the same order, and the
    whole run persists as one `COMPLETE` `SessionTranscriptTranslation`. If
    `translate` raises, or returns a different number of outcomes than
    utterances given to it (a vendor contract violation we can't safely pair
    up), this persists a `FAILED` record with no utterances and re-raises
    nothing — same shape as `run_section_classification`'s failure handling,
    so a session that hasn't been translated yet stays distinguishable from
    one whose translation run failed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)

    try:
        outcomes = await translate(session_id, utterances, document_language)
        if len(outcomes) != len(utterances):
            raise ValueError(f"translate() returned {len(outcomes)} outcomes for {len(utterances)} utterances")
        translated_utterances = [
            TranslatedUtterance(
                utterance_id=utterance.utterance_id,
                session_id=session_id,
                start_seconds=utterance.start_seconds,
                end_seconds=utterance.end_seconds,
                speaker_tag=utterance.speaker_tag,
                verbatim_text=utterance.verbatim_text,
                cleaned_text=utterance.cleaned_text,
                original_language=outcome.original_language,
                translated_text=normalize_translated_text(
                    outcome.original_language, document_language, outcome.translated_text
                ),
            )
            for utterance, outcome in zip(utterances, outcomes, strict=True)
        ]
    except Exception as exc:
        failed = SessionTranscriptTranslation(
            session_id=session_id,
            status=TranscriptTranslationStatus.FAILED,
            engine=engine,
            document_language=document_language,
            utterances=[],
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = SessionTranscriptTranslation(
        session_id=session_id,
        status=TranscriptTranslationStatus.COMPLETE,
        engine=engine,
        document_language=document_language,
        utterances=translated_utterances,
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await save(result)
    return result
