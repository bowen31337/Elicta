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

from .alignment import divergent_spans
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
# Told that this session's raw audio is now held, and where. NFR-2.4 requires
# it to be destroyed the moment transcription and diarization both finish, and
# nothing can destroy audio whose retention was never recorded.
OnAudioRetained = Callable[[str, str], Awaitable[None]]


def build_record_path_router(
    engines: Sequence[BatchEngine],
    get_vocabulary: GetEngagementVocabulary,
    save_transcript: SaveRecordPathTranscript,
    get_transcripts: GetRecordPathTranscript,
    save_alignment: SaveSessionAlignment | None = None,
    get_alignment: GetSessionAlignment | None = None,
    on_audio_retained: OnAudioRetained | None = None,
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
        if on_audio_retained is not None:
            await on_audio_retained(session_id, payload.audio_ref)
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
    get_alignment: GetSessionAlignment | None = None,
    on_audio_retained: OnAudioRetained | None = None,
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
        # Before anything is dispatched: this is the moment the service takes
        # custody of the raw audio, and the moment its eventual destruction
        # (NFR-2.4) becomes something that can be owed.
        if on_audio_retained is not None:
            await on_audio_retained(meeting_id, payload.audio_ref)
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

    if get_alignment is not None:

        @router.get(
            "/{meeting_id}/record/divergences",
            response_model=SessionAlignment,
        )
        async def get_meeting_record_divergences(meeting_id: str) -> SessionAlignment:
            """The divergent/low-confidence spans from this meeting's alignment (PRD FR-2.8).

            Reuses `SessionAlignment` as the response shape rather than a
            bespoke schema — `meeting_id` already lands in its `session_id`
            field, the same way the async job path above already treats a
            meeting id as the session id for every other persisted record.
            Narrows `spans` down to `divergent_spans(alignment)` so a debrief
            reviewer only sees what PRD FR-2.8 requires surfacing, not every
            aligned span including the ones the two engines agreed on.
            """

            alignment = await get_alignment(meeting_id)
            if alignment is None:
                raise HTTPException(
                    status_code=404, detail="record-path alignment not found"
                )
            return alignment.model_copy(update={"spans": divergent_spans(alignment)})

    return router
