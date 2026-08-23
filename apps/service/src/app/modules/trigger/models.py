"""Wire shapes for the live utterance intake."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UtteranceRequest(BaseModel):
    """One finalised utterance, as the gate sees it (PRD FR-5.1).

    Finalised, not interim. FR-5.9's speculative drafting works on interim
    hypotheses, but a nudge raised from a hypothesis the recogniser then
    revises is a question about something nobody said.
    """

    text: str = Field(min_length=1)
    #: Who said it, when the source can tell. The gate does not use it yet;
    #: it is recorded because a trigger fired on the operator's own speech is
    #: a precision bug that is invisible without it.
    speaker: str | None = None


class UtteranceAccepted(BaseModel):
    """What the gate did with it.

    Answers whether it fired *and* whether anything was surfaced, because
    those come apart constantly: FR-5.8 refuses most hits, and an intake that
    reported only "accepted" would make a working rate limit indistinguishable
    from a broken gate.
    """

    meeting_id: str
    triggered: bool
    trigger_reason: str | None = None
    surfaced: bool = False
    nudge_id: str | None = None
