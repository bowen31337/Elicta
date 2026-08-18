"""Debrief session package: opens a meeting's debrief conversation (PRD FR-7.1).

`build_debrief_session_router` exposes `POST /api/meetings/{meeting_id}/debrief/start`,
which opens a `DebriefConversationSession` configured the opposite way from
the live nudge assistant: streaming enabled, no length cap, no latency
budget. It takes the underlying streaming conversation open and the
persistence write as injected callables, since neither the vendor SDK
client nor a durable store lives in this package — whoever wires the app
factory supplies the real implementations and mounts the returned router.
"""

from __future__ import annotations

from app.modules.debrief.session.models import DebriefConversationSession, DebriefSessionStatus
from app.modules.debrief.session.router import build_debrief_session_router
from app.modules.debrief.session.service import (
    OpenStreamingConversation,
    SaveDebriefConversationSession,
    open_debrief_conversation,
)

__all__ = [
    "DebriefConversationSession",
    "DebriefSessionStatus",
    "OpenStreamingConversation",
    "SaveDebriefConversationSession",
    "build_debrief_session_router",
    "open_debrief_conversation",
]
