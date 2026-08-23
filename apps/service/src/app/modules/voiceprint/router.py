"""`/api/operator/voiceprint` — enrolling the operator's voice (PRD FR-1.5).

Three routes on one resource, because there is exactly one print per operator:
read its status, replace it, remove it. `POST` rather than `PUT` only because
the body is a sample and the response is a status — the operation is an upsert
either way, which is what the table's unique index on `operator_id` intends.

**The sample is never stored.** FR-1.7 forbids raw audio reaching persistent
storage, and this is the one route that receives audio outside the recording
path's held-and-destroyed lifecycle. The bytes exist inside the handler, become
an embedding, and go out of scope. Nothing here writes them anywhere, and this
module's tests assert that by driving the route against a backend that would
record it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .embedding import MAX_ENROLMENT_MS, MIN_ENROLMENT_MS, MODEL_NAME, SAMPLE_RATE
from .models import EnrolmentRequest, VoiceprintStatus
from .service import (
    DEFAULT_OPERATOR_ID,
    EnrolmentRefused,
    ForgetVoiceprint,
    GetVoiceprint,
    Now,
    SaveVoiceprint,
    decode_sample,
    enrol_operator,
    is_usable,
)


def build_voiceprint_router(
    get_voiceprint: GetVoiceprint,
    save_voiceprint: SaveVoiceprint,
    forget_voiceprint: ForgetVoiceprint,
    *,
    operator_id: str = DEFAULT_OPERATOR_ID,
    now: Now | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/operator", tags=["operator-voiceprint"])

    async def _status() -> VoiceprintStatus:
        voiceprint = await get_voiceprint(operator_id)
        if voiceprint is None:
            return VoiceprintStatus(
                enrolled=False,
                max_sample_seconds=MAX_ENROLMENT_MS // 1000,
                min_sample_seconds=MIN_ENROLMENT_MS // 1000,
            )
        return VoiceprintStatus(
            enrolled=True,
            sample_seconds=round(voiceprint.sample_duration_ms / 1000, 1),
            embedding_model=voiceprint.embedding_model,
            enrolled_at=voiceprint.enrolled_at,
            max_sample_seconds=MAX_ENROLMENT_MS // 1000,
            min_sample_seconds=MIN_ENROLMENT_MS // 1000,
            usable=is_usable(voiceprint),
        )

    @router.get("/voiceprint", response_model=VoiceprintStatus)
    async def read_voiceprint() -> VoiceprintStatus:
        """Whether this operator is enrolled, and with what.

        200 with `enrolled: false` rather than 404. Not being enrolled is a
        normal state of the capture screen, not a missing resource, and a 404
        here would make "no enrolment yet" and "the service is not reachable"
        look the same to the panel.
        """

        return await _status()

    @router.post("/voiceprint", response_model=VoiceprintStatus, status_code=201)
    async def create_voiceprint(payload: EnrolmentRequest) -> VoiceprintStatus:
        """Enrol from one sample, replacing any earlier print.

        422 rather than 400 for a sample that cannot be embedded: the request
        is well-formed and the *audio* is the problem, and the detail is
        written for the operator because the capture screen shows it verbatim.
        """

        try:
            audio = decode_sample(payload.pcm)
            await enrol_operator(
                operator_id,
                audio,
                save_voiceprint,
                **({} if now is None else {"now": now}),
            )
        except EnrolmentRefused as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        return await _status()

    @router.delete("/voiceprint", status_code=204)
    async def delete_voiceprint() -> None:
        """Remove the enrolment.

        204 whether or not there was one to remove. The caller asked for a
        state, not for a transaction, and answering 404 for "already not
        enrolled" would make the panel report a failure for getting what it
        asked for.
        """

        await forget_voiceprint(operator_id)

    return router


__all__ = [
    "MAX_ENROLMENT_MS",
    "MIN_ENROLMENT_MS",
    "MODEL_NAME",
    "SAMPLE_RATE",
    "build_voiceprint_router",
]
