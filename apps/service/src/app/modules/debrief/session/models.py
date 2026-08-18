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
