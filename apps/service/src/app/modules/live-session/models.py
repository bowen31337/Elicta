"""Domain types for starting a meeting's live capture session (PRD "Live Session" domain).

`SessionStart` is the persisted-ish record a `StartSession` callable hands
back once a live capture session has been opened for a meeting: a fresh
`session_id` the caller uses to correlate whatever follows (the second-screen
event stream, a later stop-and-flush) plus the moment capture began. It
carries no coverage state, nudge history, or transcript reference -- those
belong to the modules that own them, not to the act of starting a session.

`SessionStop` is its counterpart, and it did not exist for a long time while
two separate doc comments in the desktop described it as though it did. The
panel's Stop button has always posted to
``POST /api/meetings/{id}/session/stop``; the service has never served that
path, so every press was a 404 the panel swallowed. Its `session_id` is
optional for the one honest reason: an operator can press Stop on a meeting
with no session open, and answering with an invented id would be a lie about
work that was never done, while refusing would leave the button doing nothing
again.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SessionStart(BaseModel):
    """A newly opened live capture session for one meeting."""

    session_id: str
    meeting_id: str
    started_at: datetime


class SessionStop(BaseModel):
    """A live capture session that has been closed for one meeting.

    `session_id` is `None` when there was nothing open to close. That is a
    success, not a failure: the operator asked for the recording to be over
    and it is over. The distinction is kept rather than smoothed away because
    a caller reconciling what it recorded against what the service saw needs
    to know whether this call is the one that ended a session.
    """

    session_id: str | None
    meeting_id: str
    stopped_at: datetime
