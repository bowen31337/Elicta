"""Builds the full-session transcript artifact, speaker-attributed and timestamped (PRD FR-8.1).

`run_transcript_translation` (PRD FR-8.7a, `debrief/pipeline/translation.py`)
is the last stage before section classification: it already derives one
`TranslatedUtterance` per diarized, cleaned utterance, each carrying its
`speaker_tag`, `start_seconds`/`end_seconds`, its original-language wording,
and — where the utterance's spoken language differs from the session's
`document_language` — a translation alongside that untouched original.
`build_transcript_artifact` turns that translation run's utterances into the
durable transcript artifact itself: one entry per utterance, in transcript
order, with the run's `document_language` persisted as this artifact's
`artifact_language`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.modules.debrief.pipeline.models import (
    SessionTranscriptTranslation,
    TranscriptTranslationStatus,
)

from .models import (
    TranscriptArtifact,
    TranscriptArtifactEntry,
    TranscriptArtifactStatus,
)

SaveTranscriptArtifact = Callable[[TranscriptArtifact], Awaitable[None]]


async def build_transcript_artifact(
    translation: SessionTranscriptTranslation,
    save: SaveTranscriptArtifact,
    *,
    generated_at: datetime | None = None,
) -> TranscriptArtifact:
    """Build and persist the transcript artifact for one translation run (PRD FR-8.1).

    Requires `translation` to be a `COMPLETE` `SessionTranscriptTranslation`
    — a transcript built from a run that never translated anything would
    have no utterances to render at all, indistinguishable from a session
    with nothing said yet, so this persists a `FAILED` transcript carrying
    `translation.error` instead. On success, every utterance becomes one
    `TranscriptArtifactEntry` in the same order the translation run produced
    them, keeping its speaker_tag, its start/end timestamps, and both its
    original-language wording and (where present) its translation — the same
    both-original-and-translation shape `ArtifactCitation` carries elsewhere
    in this pipeline (PRD FR-8.7a) — rather than collapsing to a single
    rendering of the text.
    """

    generated_at = generated_at or datetime.now(UTC)

    if translation.status != TranscriptTranslationStatus.COMPLETE:
        failed = TranscriptArtifact(
            session_id=translation.session_id,
            status=TranscriptArtifactStatus.FAILED,
            artifact_language=translation.document_language,
            entries=[],
            generated_at=generated_at,
            error=translation.error or "transcript translation did not complete",
        )
        await save(failed)
        return failed

    entries = [
        TranscriptArtifactEntry(
            utterance_id=utterance.utterance_id,
            speaker_tag=utterance.speaker_tag,
            start_seconds=utterance.start_seconds,
            end_seconds=utterance.end_seconds,
            quoted_text=utterance.verbatim_text,
            original_language=utterance.original_language,
            translated_text=utterance.translated_text,
        )
        for utterance in translation.utterances
    ]

    result = TranscriptArtifact(
        session_id=translation.session_id,
        status=TranscriptArtifactStatus.COMPLETE,
        artifact_language=translation.document_language,
        entries=entries,
        generated_at=generated_at,
    )
    await save(result)
    return result
