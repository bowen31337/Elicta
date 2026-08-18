"""Domain types for the per-meeting recompiled question bank HTTP surface (PRD FR-4.8).

`BankCandidate` is a deliberately small slice of the full compiled-candidate
row shape (architecture section 3.6: template_section, trigger_types,
phrasing, stub, lang, priority, requires, authority_match, source_doc,
embedding) -- this package only needs the fields `recompile.py` reasons about
(`priority`, ordering) plus enough to render a candidate (`phrasing`,
`template_section`). The rest of that row shape belongs to whichever package
owns compiling candidates from engagement documents; this package only
re-ranks an already-compiled set for one meeting.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BankCandidate(BaseModel):
    """One candidate question in a meeting's recompiled bank (PRD FR-4.8, architecture section 3.6).

    `priority` orders candidates within the bank -- lower is ranked higher --
    mirroring the ascending `impact_rank` convention `OpenQuestion` already
    uses elsewhere in this codebase (`debrief/pipeline/models.py`).
    `inherited_from_open_question` is `True` only for a candidate
    `recompile_meeting_bank` derived directly from a prior meeting's open
    question rather than from the engagement's own compiled candidate set, so
    a caller can render "carried forward from last time" distinctly from a
    freshly compiled candidate.
    """

    id: str
    template_section: str
    phrasing: str
    priority: int = Field(ge=1)
    inherited_from_open_question: bool = False


class MeetingQuestionBank(BaseModel):
    """The fresh, per-meeting recompiled question bank (PRD FR-4.8).

    Recomputed for every meeting rather than reused across an engagement's
    meetings -- "the bank" a live meeting reads from is always this
    meeting's own recompile, not the engagement's original compile from
    `POST /api/engagements/{id}/bank/compile`.
    """

    meeting_id: str
    candidates: list[BankCandidate]
    generated_at: datetime
