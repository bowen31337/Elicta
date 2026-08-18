"""Domain types for a meeting's debrief conversation session (PRD FR-7.1).

Debrief mode is the deliberate opposite trade-off from the live path: the
live nudge assistant always renders complete, never streaming (FR-6.4),
caps message length (FR-6.1), and runs inside a latency budget (NFR-1)
because it competes with the operator's attention during a live call. None
of that applies once the meeting has ended, so a `DebriefConversationSession`
always opens with `streaming_enabled=True` and both `length_cap` and
`latency_budget_seconds` left `None` — there is no bound to report here, not
an unset one.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class DebriefSessionStatus(str, Enum):
    """Lifecycle state of a debrief conversation session.

    Only `OPEN` is ever produced by this package — closing or resuming a
    debrief conversation is a separate concern from opening one.
    """

    OPEN = "open"


class DebriefConversationSession(BaseModel):
    """One meeting's open debrief conversation (PRD FR-7.1).

    `conversation_ref` is the opaque handle the injected
    `OpenStreamingConversation` call returns for the underlying streaming
    conversation (backed by the Claude Agent SDK per the PRD) — this package
    never inspects it, just carries it so a later message-exchange stage can
    address the right conversation.
    """

    session_id: str
    meeting_id: str
    conversation_ref: str
    status: DebriefSessionStatus
    streaming_enabled: bool
    length_cap: int | None
    latency_budget_seconds: float | None
    opened_at: datetime
