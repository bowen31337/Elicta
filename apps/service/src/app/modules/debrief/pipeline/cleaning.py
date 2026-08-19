"""Orchestrates cleaning the diarized transcript: disfluency removal, vocabulary correction, punctuation (PRD FR-7.2).

`run_transcript_cleaning` takes the cleaning pass itself as an injected
callable rather than importing a concrete NLP/LLM vendor client directly,
mirroring `service.py`'s `DiarizeAudio` and `retention.py`'s `DeleteAudio`:
the vendor is still an open decision, and no durable store exists yet in
this codebase. Whoever wires the app factory supplies the real
implementation.

This stage runs after diarization (PRD step 2) and after the raw audio is
discarded (PRD step 3) — it operates on the `Utterance`s diarization already
produced, text only, never on audio. Its whole job is to persist a cleaned
rendering of each utterance's text *alongside* the verbatim original it was
diarized with, never in place of it, so later debrief stages (section
classification, the BMAD analyst chain, citations) can choose which
rendering they need and an operator can always recover exactly what was
said.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .models import (
    CleanedUtterance,
    SessionTranscriptCleaning,
    TranscriptCleaningStatus,
    Utterance,
)

CleanTranscript = Callable[[str, list[Utterance]], Awaitable[list[str]]]
SaveSessionTranscriptCleaning = Callable[[SessionTranscriptCleaning], Awaitable[None]]


async def run_transcript_cleaning(
    session_id: str,
    utterances: list[Utterance],
    engine: str,
    clean: CleanTranscript,
    save: SaveSessionTranscriptCleaning,
    *,
    requested_at: datetime | None = None,
) -> SessionTranscriptCleaning:
    """Clean every utterance's text and persist it alongside its verbatim original (PRD FR-7.2).

    On success, every utterance in `utterances` becomes a `CleanedUtterance`
    carrying both `verbatim_text` (the diarized `Utterance.text`, untouched)
    and `cleaned_text` (what `clean` returned for it, in the same order),
    and the whole run persists as one `COMPLETE` `SessionTranscriptCleaning`.
    If `clean` raises, or returns a different number of cleaned texts than
    utterances given to it (a vendor contract violation we can't safely
    pair up), this persists a `FAILED` record with no utterances and
    re-raises nothing — same shape as `run_diarization`'s failure handling,
    so a session that hasn't been cleaned yet stays distinguishable from one
    whose cleaning run failed.
    """

    requested_at = requested_at or datetime.now(UTC)

    try:
        cleaned_texts = await clean(session_id, utterances)
        if len(cleaned_texts) != len(utterances):
            raise ValueError(
                f"clean() returned {len(cleaned_texts)} cleaned texts for {len(utterances)} utterances"
            )
        cleaned_utterances = [
            CleanedUtterance(
                utterance_id=utterance.utterance_id,
                session_id=session_id,
                start_seconds=utterance.start_seconds,
                end_seconds=utterance.end_seconds,
                speaker_tag=utterance.speaker_tag,
                verbatim_text=utterance.text,
                cleaned_text=cleaned_text,
            )
            for utterance, cleaned_text in zip(utterances, cleaned_texts, strict=True)
        ]
    except Exception as exc:
        failed = SessionTranscriptCleaning(
            session_id=session_id,
            status=TranscriptCleaningStatus.FAILED,
            engine=engine,
            utterances=[],
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = SessionTranscriptCleaning(
        session_id=session_id,
        status=TranscriptCleaningStatus.COMPLETE,
        engine=engine,
        utterances=cleaned_utterances,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
