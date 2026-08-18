"""HTTP surface for record-path batch re-transcription (PRD FR-2.5/2.6).

Both `build_record_path_router` (synchronous, session-keyed) and
`build_meeting_transcription_router` (async job, meeting-keyed) take the
batch engines and the persistence reads/writes as injected callables rather
than importing a concrete ASR vendor client or storage layer, since neither
lives in this package. Whoever wires the app factory (out of this feature's
footprint) supplies the real implementations and mounts the returned
routers.

`engines` is a `Sequence[BatchEngine]` (PRD FR-2.6 wants two independent
engines per session) rather than a single transcriber, so both endpoints
now deal in lists of `RecordPathTranscript` — one entry per configured
engine — instead of a single transcript.
"""

from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, HTTPException

from .models import RecordPathTranscript, RecordPathTranscriptionJob, SessionAlignment
from .schemas import RecordPathTranscriptionRequest
from .service import (
    BatchEngine,
    GetEngagementVocabulary,
    GetRecordPathTranscript,
    SaveRecordPathTranscript,
    SaveSessionAlignment,
    SaveTranscriptionJob,
    ScheduleTranscriptionWork,
    run_record_path_transcription,
    start_record_path_transcription_job,
)

GetSessionAlignment = Callable[[str], Awaitable[SessionAlignment | None]]


def build_record_path_router(
    engines: Sequence[BatchEngine],
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    get_transcripts: GetRecordPathTranscript,
    save_alignment: SaveSessionAlignment | None = None,
    get_alignment: GetSessionAlignment | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["record-path-transcription"])

    @router.post(
        "/{session_id}/record-path-transcript",
        response_model=list[RecordPathTranscript],
        status_code=201,
    )
    async def create_record_path_transcript(
        session_id: str, payload: RecordPathTranscriptionRequest
    ) -> list[RecordPathTranscript]:
        return await run_record_path_transcription(
            session_id,
            payload.audio_ref,
            engines,
            save_transcript,
            get_vocabulary,
            save_alignment=save_alignment,
        )

    @router.get(
        "/{session_id}/record-path-transcript",
        response_model=list[RecordPathTranscript],
    )
    async def get_record_path_transcript(session_id: str) -> list[RecordPathTranscript]:
        transcripts = await get_transcripts(session_id)
        if not transcripts:
            raise HTTPException(
                status_code=404, detail="record-path transcript not found"
            )
        return transcripts

    if get_alignment is not None:

        @router.get(
            "/{session_id}/record-path-alignment",
            response_model=SessionAlignment,
        )
        async def get_record_path_alignment(session_id: str) -> SessionAlignment:
            alignment = await get_alignment(session_id)
            if alignment is None:
                raise HTTPException(
                    status_code=404, detail="record-path alignment not found"
                )
            return alignment

    return router


def build_meeting_transcription_router(
    engines: Sequence[BatchEngine],
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    save_job: SaveTranscriptionJob,
    schedule: ScheduleTranscriptionWork,
    save_alignment: SaveSessionAlignment | None = None,
) -> APIRouter:
    """Async, job-based entry point for starting one meeting's record-path run.

    A separate router (and separate dependency set) from
    `build_record_path_router` above: that one transcribes a session
    synchronously and responds once every batch engine finishes, while this
    one is keyed by meeting rather than session and returns a job handle
    immediately (202) so a caller isn't left holding an HTTP connection open
    for a full-meeting batch run.
    """

    router = APIRouter(prefix="/api/meetings", tags=["record-path-transcription"])

    @router.post(
        "/{meeting_id}/record/transcribe",
        response_model=RecordPathTranscriptionJob,
        status_code=202,
    )
    async def start_meeting_record_path_transcription(
        meeting_id: str, payload: RecordPathTranscriptionRequest
    ) -> RecordPathTranscriptionJob:
        return await start_record_path_transcription_job(
            meeting_id,
            payload.audio_ref,
            engines,
            get_vocabulary,
            save_transcript,
            save_job,
            schedule,
            save_alignment=save_alignment,
        )

    return router
