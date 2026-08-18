"""Orchestrates one record-path batch re-transcription run (PRD FR-2.5).

`run_record_path_transcription` takes the highest-accuracy engine call and
the persistence write as injected callables rather than importing a concrete
ASR vendor client or storage layer directly, since neither lives in this
package (`app/modules/asr-record`) — the vendor is still an open decision
(PRD D4) and no durable store exists yet in this codebase. Whoever wires the
app factory (out of this feature's footprint) supplies the real
implementations and mounts the router built on top of this.

`get_vocabulary` is injected the same way: the engagement's custom
vocabulary (client name, product names, internal systems, acronyms) lives
outside this package too, but PRD FR-2.9 requires it be sent as keyterm
prompting on the record path exactly as it is on the live path, so every
batch request here fetches it and passes it to `transcribe`.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import (
    BatchTranscriptionOutput,
    RecordPathTranscript,
    TranscriptionStatus,
)

BatchTranscriber = Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]
SaveRecordPathTranscript = Callable[[RecordPathTranscript], Awaitable[None]]
GetRecordPathTranscript = Callable[[str], Awaitable[RecordPathTranscript | None]]
GetEngagementVocabulary = Callable[[str], Awaitable[list[str]]]


async def run_record_path_transcription(
    session_id: str,
    audio_ref: str,
    transcribe: BatchTranscriber,
    save: SaveRecordPathTranscript,
    get_vocabulary: GetEngagementVocabulary,
    *,
    requested_at: datetime | None = None,
) -> RecordPathTranscript:
    """Re-transcribe one full session at the highest available accuracy.

    Fetches the engagement's custom vocabulary and sends it to the engine as
    keyterm prompting (PRD FR-2.9) on every batch request, mirroring the
    live path.

    Persists the outcome either way: on success, a `COMPLETE` transcript
    covering the full session; on the engine raising, a `FAILED` record
    carrying the error, so a batch run over an hour-long session that fails
    partway through is visible rather than leaving no record-path transcript
    at all. The original exception is re-raised after the failure is
    recorded, so callers still see the run did not succeed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)

    try:
        keyterms = await get_vocabulary(session_id)
        output = await transcribe(session_id, audio_ref, keyterms)
    except Exception as exc:
        failed = RecordPathTranscript(
            session_id=session_id,
            status=TranscriptionStatus.FAILED,
            engine="",
            segments=[],
            text="",
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await save(failed)
        raise

    transcript = RecordPathTranscript(
        session_id=session_id,
        status=TranscriptionStatus.COMPLETE,
        engine=output.engine,
        segments=output.segments,
        text=output.text,
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await save(transcript)
    return transcript
