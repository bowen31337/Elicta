"""HTTP surface for a meeting's debrief conversation (PRD FR-7.1, FR-7.4).

`build_debrief_session_router` takes the streaming conversation open, the
live-mode nudge signal load, the persistence read/write, and the message
send as injected callables rather than importing a concrete vendor client or
storage layer directly, since none of them live in this package
(`app/modules/debrief/session`). Whoever wires the app factory (out of this
feature's footprint) supplies the real implementations and mounts the
returned router.
"""

from __future__ import annotations

from fastapi import APIRouter

from .models import DebriefConversationSession, DebriefMessageRequest
from .service import (
    LoadDebriefConversationSession,
    LoadLiveModeNudgeSignal,
    OpenStreamingConversation,
    SaveDebriefConversationSession,
    SendDebriefMessage,
    open_debrief_conversation,
    send_debrief_message,
)


def build_debrief_session_router(
    open_conversation: OpenStreamingConversation,
    load_nudge_signal: LoadLiveModeNudgeSignal,
    save: SaveDebriefConversationSession,
    load_session: LoadDebriefConversationSession,
    send_message: SendDebriefMessage,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["debrief-session"])

    @router.post(
        "/{meeting_id}/debrief/start",
        response_model=DebriefConversationSession,
        status_code=201,
    )
    async def start_debrief_session(meeting_id: str) -> DebriefConversationSession:
        return await open_debrief_conversation(
            meeting_id, open_conversation, load_nudge_signal, save
        )

    @router.post(
        "/{meeting_id}/debrief/message",
        response_model=DebriefConversationSession,
        status_code=200,
    )
    async def send_message_to_debrief_session(
        meeting_id: str, body: DebriefMessageRequest
    ) -> DebriefConversationSession:
        return await send_debrief_message(
            meeting_id, body.message, load_session, send_message, save
        )

    return router
