"""HTTP surface for record-path batch re-transcription (PRD FR-2.5).

`build_record_path_router` takes the batch engine call and the
persistence reads/writes as injected callables rather than importing a
concrete ASR vendor client or storage layer, since neither lives in this
package. Whoever wires the app factory (out of this feature's footprint)
supplies the real implementations and mounts the returned router.
"""

from fastapi import APIRouter, HTTPException

from .models import RecordPathTranscript
from .schemas import RecordPathTranscriptionRequest
from .service import (
    BatchTranscriber,
    GetRecordPathTranscript,
    SaveRecordPathTranscript,
    run_record_path_transcription,
)


def build_record_path_router(
    transcribe: BatchTranscriber,
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
            session_id, payload.audio_ref, transcribe, save_transcript
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
