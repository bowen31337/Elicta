"""HTTP surface for opening a meeting's debrief conversation (PRD FR-7.1).

`build_debrief_session_router` takes the streaming conversation open and the
persistence write as injected callables rather than importing a concrete
vendor client or storage layer directly, since neither lives in this
package (`app/modules/debrief/session`). Whoever wires the app factory
(out of this feature's footprint) supplies the real implementations and
mounts the returned router.
"""

from __future__ import annotations

from fastapi import APIRouter

from .models import DebriefConversationSession
from .service import (
    OpenStreamingConversation,
    SaveDebriefConversationSession,
    open_debrief_conversation,
)


def build_debrief_session_router(
    open_conversation: OpenStreamingConversation,
    save: SaveDebriefConversationSession,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["debrief-session"])

    @router.post(
        "/{meeting_id}/debrief/start",
        response_model=DebriefConversationSession,
        status_code=201,
    )
    async def start_debrief_session(meeting_id: str) -> DebriefConversationSession:
        return await open_debrief_conversation(meeting_id, open_conversation, save)

    return router
