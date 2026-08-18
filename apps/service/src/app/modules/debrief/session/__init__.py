"""Debrief session package: opens a meeting's debrief conversation (PRD FR-7.1, FR-7.4).

`build_debrief_session_router` exposes `POST /api/meetings/{meeting_id}/debrief/start`,
which opens a `DebriefConversationSession` configured the opposite way from
the live nudge assistant: streaming enabled, no length cap, no latency
budget. It also inherits the live-mode signal into that session (FR-7.4):
every nudge that fired during the call, tagged with whichever disposition —
fired, taken, or parked — it ended live mode with. It takes the underlying
streaming conversation open, the live-mode nudge signal load, and the
persistence write as injected callables, since none of the vendor SDK
client, the live-mode nudge store, or a durable store lives in this
package — whoever wires the app factory supplies the real implementations
and mounts the returned router.
"""

from __future__ import annotations

from app.modules.debrief.session.models import (
    DebriefConversationSession,
    DebriefSessionStatus,
    NudgeDisposition,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.router import build_debrief_session_router
from app.modules.debrief.session.service import (
    LoadLiveModeNudgeSignal,
    OpenStreamingConversation,
    SaveDebriefConversationSession,
    open_debrief_conversation,
)

__all__ = [
    "DebriefConversationSession",
    "DebriefSessionStatus",
    "LoadLiveModeNudgeSignal",
    "NudgeDisposition",
    "NudgeDispositionRecord",
    "OpenStreamingConversation",
    "SaveDebriefConversationSession",
    "build_debrief_session_router",
    "open_debrief_conversation",
]
