"""Domain types for a meeting's debrief conversation session (PRD FR-7.1, FR-7.4).

Debrief mode is the deliberate opposite trade-off from the live path: the
live nudge assistant always renders complete, never streaming (FR-6.4),
caps message length (FR-6.1), and runs inside a latency budget (NFR-1)
because it competes with the operator's attention during a live call. None
of that applies once the meeting has ended, so a `DebriefConversationSession`
always opens with `streaming_enabled=True` and both `length_cap` and
`latency_budget_seconds` left `None` — there is no bound to report here, not
an unset one.

The live path still leaves a trace worth carrying forward, though: every
nudge that fired during the call, and what became of it. `NudgeDisposition`
and `NudgeDispositionRecord` capture that trace so the debrief thread opens
already knowing which nudges fired, which were taken, and which were parked
(FR-7.4).

`DebriefMessage` carries one turn of the conversation the way the underlying
streaming conversation itself represents it — a list of raw content blocks,
not the plain-text extraction of them. The debrief session is multi-turn
and reads a full transcript, so it outgrows a single context window and
relies on the underlying conversation's server-side compaction; that
compaction attaches its own state to the response's content blocks, and a
history that stores only the extracted text silently drops that state the
next time it is replayed back into the conversation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class DebriefSessionStatus(str, Enum):
    """Lifecycle state of a debrief conversation session.

    Only `OPEN` is ever produced by this package — closing or resuming a
    debrief conversation is a separate concern from opening one.
    """

    OPEN = "open"


class NudgeDisposition(str, Enum):
    """How one live-mode nudge was resolved by the time the call ended (PRD FR-7.4).

    `FIRED` is itself a disposition, not a placeholder for a missing one —
    it means the nudge surfaced and the call ended before the operator took
    or parked it.
    """

    FIRED = "fired"
    TAKEN = "taken"
    PARKED = "parked"


class NudgeDispositionRecord(BaseModel):
    """One live-mode nudge as inherited into the debrief thread (PRD FR-7.4).

    Mirrors the live nudge assistant's own surfaced nudge (a stub headline,
    the full question, and the reason it fired — PRD FR-6.2/6.3/5.11) plus
    the `disposition` it ended live mode with, so the debrief conversation
    can discuss a specific nudge without a further round trip to the
    live-mode store.
    """

    nudge_id: str
    stub: str
    question: str
    trigger_reason: str
    fired_at: datetime
    disposition: NudgeDisposition


class DebriefMessageRole(str, Enum):
    """Who authored one turn of the debrief conversation history."""

    USER = "user"
    ASSISTANT = "assistant"


class DebriefMessage(BaseModel):
    """One turn of the debrief conversation, persisted verbatim.

    `content` is the underlying streaming conversation's own list of content
    blocks — for an assistant turn, the full `response.content` the Claude
    Agent SDK returns — rather than a text extraction of it. This package
    never inspects the blocks, only carries them, since it has no way to
    know which ones the vendor's server-side compaction has attached state
    to.
    """

    role: DebriefMessageRole
    content: list[dict[str, Any]]
    recorded_at: datetime


class DebriefMessageRequest(BaseModel):
    """Request body for sending a free-form message into an open debrief conversation."""

    message: str


class DebriefConversationSession(BaseModel):
    """One meeting's open debrief conversation (PRD FR-7.1, FR-7.4).

    `conversation_ref` is the opaque handle the injected
    `OpenStreamingConversation` call returns for the underlying streaming
    conversation (backed by the Claude Agent SDK per the PRD) — this package
    never inspects it, just carries it so a later message-exchange stage can
    address the right conversation.

    `nudge_dispositions` is the inherited live-mode signal (FR-7.4): every
    nudge that fired during the call, each carrying whichever disposition —
    fired, taken, or parked — it ended live mode with. It is persisted as
    part of the session itself rather than fetched separately, so the
    debrief context always has that history the moment the session opens.

    `history` is every turn exchanged in the conversation so far, in order,
    each carrying its raw content blocks rather than extracted text (see
    `DebriefMessage`). It opens empty and grows one user turn plus one
    assistant turn per message sent.
    """

    session_id: str
    meeting_id: str
    conversation_ref: str
    status: DebriefSessionStatus
    streaming_enabled: bool
    length_cap: int | None
    latency_budget_seconds: float | None
    opened_at: datetime
    nudge_dispositions: list[NudgeDispositionRecord]
    history: list[DebriefMessage]
