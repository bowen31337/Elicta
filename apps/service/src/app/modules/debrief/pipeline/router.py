"""HTTP surface for writing one requirement citation row to a session's citations table (PRD FR-8.7, FR-2.7).

`build_citation_row_router` takes the persistence write as an injected
callable, mirroring every other router in this codebase
(`debrief/session/router.py`, `debrief/artifacts/router.py`): no durable
store lives in this package. Whoever wires the app factory (out of this
feature's footprint) supplies the real implementation and mounts the
returned router.

`CitationRow.utterance_id` in `models.py` is a required `str`, never
`str | None`. That means a write whose JSON body carries a null
`utterance_id` never reaches `write_citation_row`'s body at all — FastAPI
validates the request against the `CitationRow` schema first and rejects it
with 422 before this endpoint's own code runs. Citation integrity is
enforced by the schema every write is validated against, not by trusting
whichever caller (the BMAD analyst chain via `citations.py`, or this direct
API) to have supplied a real id — the same "structural, not prompt-
dependent" grounding `resolve_citations` and `build_citation_rows` rely on
elsewhere in this package.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import AudioDestructionEvent, CitationRow, DebriefCompletion

SaveCitationRow = Callable[[CitationRow], Awaitable[None]]
GetAudioDestruction = Callable[[str], Awaitable[AudioDestructionEvent | None]]


def build_citation_row_router(save: SaveCitationRow) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["debrief-citations"])

    @router.post("/{session_id}/citations", response_model=CitationRow, status_code=201)
    async def write_citation_row(session_id: str, row: CitationRow) -> CitationRow:
        await save(row)
        return row

    return router


def build_audio_destruction_router(get_event: GetAudioDestruction) -> APIRouter:
    """Build the audio-destruction read route (PRD NFR-2.4).

    NFR-2.4 does not just require the raw audio to be discarded; it requires
    the discard to be *observable*, which is why `AudioDestructionEvent` is
    persisted whether the deletion succeeded or failed. It was persisted and
    then served back nowhere, so the one screen whose job is to tell a
    reviewer what happened to the audio had nothing to read.

    A 404 means no attempt has been made yet — the session is still being
    transcribed, or was never captured. That is deliberately distinct from a
    `FAILED` event, which means the audio may still be sitting there and
    somebody needs to know.
    """

    router = APIRouter(prefix="/api/sessions", tags=["audio-lifecycle"])

    @router.get(
        "/{session_id}/audio-destruction",
        response_model=AudioDestructionEvent,
        status_code=200,
    )
    async def get_audio_destruction(session_id: str) -> AudioDestructionEvent:
        event = await get_event(session_id)
        if event is None:
            raise HTTPException(status_code=404, detail="no audio destruction event")
        return event

    return router


GetDebriefCompletion = Callable[[str], Awaitable[DebriefCompletion | None]]


def build_debrief_completion_router(get_completion: GetDebriefCompletion) -> APIRouter:
    """Build the read route that says what the write-up could not produce.

    The pipeline has always recorded this — `stopped_at` names the first stage
    that did not complete — into a dictionary read only to stop the pipeline
    running twice. Serving it is what turns "recorded" into "visible", which is
    the half of the promise that was missing.

    A 404 means no debrief has run for this meeting: not yet asked for, rather
    than asked for and stopped. Reporting those the same way would put a
    failure notice on every meeting whose write-up is simply still to come.
    """

    router = APIRouter(prefix="/api/meetings", tags=["debrief-pipeline"])

    @router.get(
        "/{meeting_id}/debrief/completion",
        response_model=DebriefCompletion,
        status_code=200,
    )
    async def get_debrief_completion(meeting_id: str) -> DebriefCompletion:
        completion = await get_completion(meeting_id)
        if completion is None:
            raise HTTPException(status_code=404, detail="no debrief run for this meeting")
        return completion

    return router
