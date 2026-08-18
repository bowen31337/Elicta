"""Opens one meeting's debrief conversation session (PRD FR-7.1).

`open_debrief_conversation` takes the underlying streaming conversation open
as an injected callable (`OpenStreamingConversation`) rather than importing
the Claude Agent SDK directly, mirroring every other stage of `debrief`
(`pipeline/bmad_analyst.py`'s `RunBmadAnalystChain`, `asr-record`'s
`BatchTranscriber`): no vendor client or durable store lives in this
package. Whoever wires the app factory supplies the real implementations.

FR-7.1 fixes three properties of a debrief session that a caller never gets
to negotiate: `streaming_enabled` is always `True`, and neither `length_cap`
nor `latency_budget_seconds` is ever set to a bound — debrief mode is
deliberately the opposite trade-off from the live nudge assistant (FR-6.4
disables streaming, FR-6.1 caps length, NFR-1 puts a latency budget on the
live path). Carrying the live session's own thread and context forward into
the debrief conversation — the "same thread, same context" half of FR-7.1 —
is a separate concern and is not handled here.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import DebriefConversationSession, DebriefSessionStatus

OpenStreamingConversation = Callable[[str, str], Awaitable[str]]
SaveDebriefConversationSession = Callable[[DebriefConversationSession], Awaitable[None]]


async def open_debrief_conversation(
    meeting_id: str,
    open_conversation: OpenStreamingConversation,
    save: SaveDebriefConversationSession,
    *,
    session_id: str | None = None,
    opened_at: datetime | None = None,
) -> DebriefConversationSession:
    """Open one meeting's debrief conversation and persist it (PRD FR-7.1).

    `open_conversation` establishes the actual streaming conversation on
    whatever backs it (the Claude Agent SDK, per the PRD) and returns its
    handle as `conversation_ref`; this function never talks to that vendor
    directly. `session_id` and `opened_at` are accepted so callers (tests,
    or a caller that already has an id from elsewhere) can pin them, and
    otherwise default to a generated id and the current time.
    """

    session_id = session_id or uuid.uuid4().hex
    opened_at = opened_at or datetime.now(timezone.utc)

    conversation_ref = await open_conversation(meeting_id, session_id)

    session = DebriefConversationSession(
        session_id=session_id,
        meeting_id=meeting_id,
        conversation_ref=conversation_ref,
        status=DebriefSessionStatus.OPEN,
        streaming_enabled=True,
        length_cap=None,
        latency_budget_seconds=None,
        opened_at=opened_at,
    )
    await save(session)
    return session
