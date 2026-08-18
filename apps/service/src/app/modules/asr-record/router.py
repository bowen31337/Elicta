"""HTTP surface for record-path batch re-transcription (PRD FR-2.5).

Both `build_record_path_router` (synchronous, session-keyed) and
`build_meeting_transcription_router` (async job, meeting-keyed) take the
batch engine call and the persistence reads/writes as injected callables
rather than importing a concrete ASR vendor client or storage layer, since
neither lives in this package. Whoever wires the app factory (out of this
feature's footprint) supplies the real implementations and mounts the
returned routers.
"""

from fastapi import APIRouter, HTTPException

from .models import RecordPathTranscript, RecordPathTranscriptionJob
from .schemas import RecordPathTranscriptionRequest
from .service import (
    BatchTranscriber,
    GetEngagementVocabulary,
    GetRecordPathTranscript,
    SaveRecordPathTranscript,
    SaveTranscriptionJob,
    ScheduleTranscriptionWork,
    run_record_path_transcription,
    start_record_path_transcription_job,
)


def build_record_path_router(
    transcribe: BatchTranscriber,
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    get_transcript: GetRecordPathTranscript,
) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["record-path-transcription"])

    @router.post(
        "/{session_id}/record-path-transcript",
        response_model=RecordPathTranscript,
        status_code=201,
    )
    async def create_record_path_transcript(
        session_id: str, payload: RecordPathTranscriptionRequest
    ) -> RecordPathTranscript:
        return await run_record_path_transcription(
            session_id, payload.audio_ref, transcribe, save_transcript, get_vocabulary
        )

    @router.get(
        "/{session_id}/record-path-transcript",
        response_model=RecordPathTranscript,
    )
    async def get_record_path_transcript(session_id: str) -> RecordPathTranscript:
        transcript = await get_transcript(session_id)
        if transcript is None:
            raise HTTPException(
                status_code=404, detail="record-path transcript not found"
            )
        return transcript

    return router


def build_meeting_transcription_router(
    transcribe: BatchTranscriber,
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    save_job: SaveTranscriptionJob,
    schedule: ScheduleTranscriptionWork,
) -> APIRouter:
    """Async, job-based entry point for starting one meeting's record-path run.

    A separate router (and separate dependency set) from
    `build_record_path_router` above: that one transcribes a session
    synchronously and responds once the batch engine finishes, while this
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
            transcribe,
            get_vocabulary,
            save_transcript,
            save_job,
            schedule,
        )

    return router
