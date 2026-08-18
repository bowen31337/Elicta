"""Domain types for starting a meeting's live capture session (PRD "Live Session" domain).

`SessionStart` is the persisted-ish record a `StartSession` callable hands
back once a live capture session has been opened for a meeting: a fresh
`session_id` the caller uses to correlate whatever follows (the second-screen
event stream, a later stop-and-flush) plus the moment capture began. It
carries no coverage state, nudge history, or transcript reference -- those
belong to the modules that own them, not to the act of starting a session.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SessionStart(BaseModel):
    """A newly opened live capture session for one meeting."""

    session_id: str
    meeting_id: str
    started_at: datetime
