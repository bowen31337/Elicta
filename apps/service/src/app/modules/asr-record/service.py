"""Orchestrates record-path batch re-transcription runs (PRD FR-2.5/2.6).

`run_record_path_transcription` takes the batch engine calls and the
persistence write as injected callables rather than importing a concrete ASR
vendor client or storage layer directly, since neither lives in this package
(`app/modules/asr-record`) — the vendor is still an open decision (PRD D4)
and no durable store exists yet in this codebase. Whoever wires the app
factory (out of this feature's footprint) supplies the real implementations
and mounts the router built on top of this.

PRD FR-2.6 requires two independent batch engines run over the same retained
audio for every session, so callers pass a sequence of `BatchEngine`s (a
name paired with a `BatchTranscriber`) rather than a single transcriber. The
engines run concurrently and each one's outcome — success or failure — is
persisted as its own `RecordPathTranscript`; one engine failing does not
stop or blank out the other's result, since the whole point of running two
independent engines is that they don't share fate.

`get_vocabulary` is injected the same way: the engagement's custom
vocabulary (client name, product names, internal systems, acronyms) lives
outside this package too, but PRD FR-2.9 requires it be sent as keyterm
prompting on the record path exactly as it is on the live path, so every
batch request to every engine here fetches it once and passes it to
`transcribe`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone

from .models import (
    BatchTranscriptionOutput,
    RecordPathTranscript,
    RecordPathTranscriptionJob,
    TranscriptionJobStatus,
    TranscriptionStatus,
)

BatchTranscriber = Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]
BatchEngine = tuple[str, BatchTranscriber]
SaveRecordPathTranscript = Callable[[RecordPathTranscript], Awaitable[None]]
GetRecordPathTranscript = Callable[[str], Awaitable[list[RecordPathTranscript]]]
GetEngagementVocabulary = Callable[[str], Awaitable[list[str]]]
SaveTranscriptionJob = Callable[[RecordPathTranscriptionJob], Awaitable[None]]
ScheduleTranscriptionWork = Callable[[Callable[[], Awaitable[None]]], None]


async def run_record_path_transcription(
    session_id: str,
    audio_ref: str,
    engines: Sequence[BatchEngine],
    save: SaveRecordPathTranscript,
    get_vocabulary: GetEngagementVocabulary,
    *,
    requested_at: datetime | None = None,
) -> list[RecordPathTranscript]:
    """Re-transcribe one full session with every configured engine (PRD FR-2.6).

    Fetches the engagement's custom vocabulary once and sends it to every
    engine as keyterm prompting (PRD FR-2.9), mirroring the live path, then
    runs all engines concurrently over the same retained audio.

    Each engine's outcome is persisted independently: on success, a
    `COMPLETE` transcript tagged with that engine's name; on that engine
    raising, a `FAILED` record carrying the error. One engine failing does
    not affect the other's transcript — that independence is the point of
    running two engines rather than one — so this never raises for an
    individual engine's failure. It only raises if the shared vocabulary
    lookup itself fails, since neither engine can run without it; that case
    still persists a `FAILED` transcript per engine first, so a session
    never ends up with fewer transcripts than configured engines.
    """

    requested_at = requested_at or datetime.now(timezone.utc)

    async def persist_failure(engine_name: str, error: str) -> RecordPathTranscript:
        failed = RecordPathTranscript(
            session_id=session_id,
            status=TranscriptionStatus.FAILED,
            engine=engine_name,
            segments=[],
            text="",
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=error,
        )
        await save(failed)
        return failed

    try:
        keyterms = await get_vocabulary(session_id)
    except Exception as exc:
        for engine_name, _ in engines:
            await persist_failure(engine_name, str(exc))
        raise

    async def run_one(engine_name: str, transcribe: BatchTranscriber) -> RecordPathTranscript:
        try:
            output = await transcribe(session_id, audio_ref, keyterms)
        except Exception as exc:
            return await persist_failure(engine_name, str(exc))

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

    return list(
        await asyncio.gather(*(run_one(name, transcribe) for name, transcribe in engines))
    )


async def start_record_path_transcription_job(
    meeting_id: str,
    audio_ref: str,
    engines: Sequence[BatchEngine],
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    save_job: SaveTranscriptionJob,
    schedule: ScheduleTranscriptionWork,
    *,
    job_id: str | None = None,
    created_at: datetime | None = None,
) -> RecordPathTranscriptionJob:
    """Accept a meeting's record-path transcription request without waiting on it.

    A full-meeting batch re-transcription can run far longer than an HTTP
    caller should have to block for, unlike `run_record_path_transcription`
    above (which a caller who's fine waiting can still use directly). This
    persists a `QUEUED` job immediately and hands the actual batch run to
    `schedule` — an injected callable rather than `BackgroundTasks` or a
    concrete task queue directly, since neither the worker mechanism nor a
    durable job queue lives in this package. The caller gets back a job
    handle they can poll or correlate against once the batch run finishes.

    The scheduled work updates the job to `COMPLETE`/`FAILED` itself and
    swallows the batch failure rather than re-raising it, since by the time
    it runs there is no caller left awaiting this coroutine to propagate to.
    The job is `FAILED` only if every engine ended up failed (or the shared
    vocabulary lookup blew up before any engine could run) — each engine's
    own outcome is already visible on its own persisted transcript, so the
    job status is just the coarse "did this run produce anything usable" summary.
    """

    job_id = job_id or uuid.uuid4().hex
    created_at = created_at or datetime.now(timezone.utc)
    job = RecordPathTranscriptionJob(
        job_id=job_id,
        meeting_id=meeting_id,
        status=TranscriptionJobStatus.QUEUED,
        created_at=created_at,
    )
    await save_job(job)

    async def run_and_track() -> None:
        try:
            transcripts = await run_record_path_transcription(
                meeting_id,
                audio_ref,
                engines,
                save_transcript,
                get_vocabulary,
                requested_at=created_at,
            )
        except Exception:
            await save_job(job.model_copy(update={"status": TranscriptionJobStatus.FAILED}))
            return

        final_status = (
            TranscriptionJobStatus.FAILED
            if all(t.status == TranscriptionStatus.FAILED for t in transcripts)
            else TranscriptionJobStatus.COMPLETE
        )
        await save_job(job.model_copy(update={"status": final_status}))

    schedule(run_and_track)
    return job
