"""Opens one meeting's debrief conversation session (PRD FR-7.1, FR-7.4).

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
live path).

FR-7.4 is the other half of carrying the live session forward: the
disposition of every nudge that fired during the call — fired, taken, or
parked — is loaded via the injected `LoadLiveModeNudgeSignal` (the live-mode
nudge store lives outside this package, same reasoning as
`OpenStreamingConversation`) and persisted as part of the session itself, so
the debrief context has that history the moment it opens.

`send_debrief_message` is the other half of the conversation: it sends one
free-form message into an already-open session via the injected
`SendDebriefMessage` and appends the exchange to `history`. The assistant
turn stores `send_message`'s return value — the underlying streaming
conversation's full `response.content` — verbatim rather than an extracted
text summary of it, because the debrief session outgrows one context window
and relies on that conversation's own server-side compaction, which attaches
its state to those content blocks. Persisting anything less than the full
content silently drops that state the next time the history is replayed
back into the conversation.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from .models import (
    DebriefConversationSession,
    DebriefMessage,
    DebriefMessageRole,
    DebriefSessionStatus,
    NudgeDispositionRecord,
)

OpenStreamingConversation = Callable[[str, str], Awaitable[str]]
LoadLiveModeNudgeSignal = Callable[[str], Awaitable[list[NudgeDispositionRecord]]]
SaveDebriefConversationSession = Callable[[DebriefConversationSession], Awaitable[None]]
LoadDebriefConversationSession = Callable[[str], Awaitable[DebriefConversationSession]]
SendDebriefMessage = Callable[[str, str], Awaitable[list[dict[str, Any]]]]


async def open_debrief_conversation(
    meeting_id: str,
    open_conversation: OpenStreamingConversation,
    load_nudge_signal: LoadLiveModeNudgeSignal,
    save: SaveDebriefConversationSession,
    *,
    session_id: str | None = None,
    opened_at: datetime | None = None,
) -> DebriefConversationSession:
    """Open one meeting's debrief conversation and persist it (PRD FR-7.1, FR-7.4).

    `open_conversation` establishes the actual streaming conversation on
    whatever backs it (the Claude Agent SDK, per the PRD) and returns its
    handle as `conversation_ref`; this function never talks to that vendor
    directly. `load_nudge_signal` fetches this meeting's live-mode nudge
    dispositions, which are persisted on the session verbatim — every nudge
    that fired is inherited, regardless of how it was ultimately resolved.
    `session_id` and `opened_at` are accepted so callers (tests, or a caller
    that already has an id from elsewhere) can pin them, and otherwise
    default to a generated id and the current time.
    """

    session_id = session_id or uuid.uuid4().hex
    opened_at = opened_at or datetime.now(timezone.utc)

    conversation_ref = await open_conversation(meeting_id, session_id)
    nudge_dispositions = await load_nudge_signal(meeting_id)

    session = DebriefConversationSession(
        session_id=session_id,
        meeting_id=meeting_id,
        conversation_ref=conversation_ref,
        status=DebriefSessionStatus.OPEN,
        streaming_enabled=True,
        length_cap=None,
        latency_budget_seconds=None,
        opened_at=opened_at,
        nudge_dispositions=nudge_dispositions,
        history=[],
    )
    await save(session)
    return session


async def send_debrief_message(
    meeting_id: str,
    message: str,
    load_session: LoadDebriefConversationSession,
    send_message: SendDebriefMessage,
    save: SaveDebriefConversationSession,
    *,
    recorded_at: datetime | None = None,
) -> DebriefConversationSession:
    """Send one message into a meeting's open debrief conversation and persist the full response (PRD FR-7.1).

    `load_session` fetches the meeting's currently open session so the
    message goes to the right underlying `conversation_ref`. `send_message`
    then sends `message` on that conversation and returns the assistant's
    response as its raw content blocks — this function never extracts text
    from them, only appends the blocks to `history` exactly as received, so
    whatever server-side compaction state the vendor attached to them
    survives being persisted and later replayed back into the conversation.
    Both the user's turn and the assistant's turn are appended in the same
    update, and the whole session is re-persisted via `save`.
    """

    recorded_at = recorded_at or datetime.now(timezone.utc)

    session = await load_session(meeting_id)
    response_content = await send_message(session.conversation_ref, message)

    updated = session.model_copy(
        update={
            "history": [
                *session.history,
                DebriefMessage(
                    role=DebriefMessageRole.USER,
                    content=[{"type": "text", "text": message}],
                    recorded_at=recorded_at,
                ),
                DebriefMessage(
                    role=DebriefMessageRole.ASSISTANT,
                    content=response_content,
                    recorded_at=recorded_at,
                ),
            ]
        }
    )
    await save(updated)
    return updated
