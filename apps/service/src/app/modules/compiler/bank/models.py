"""Domain types for the per-meeting recompiled question bank (PRD FR-4.8).

`BankCandidate` is a deliberately small slice of the full compiled-candidate
shape the candidates table carries (architecture section 3.6: template_section,
trigger_types, phrasing, stub, lang, priority, requires, authority_match,
source_doc, embedding) — this package only needs the fields `recompile.py`
actually reasons about (`priority`, ordering) plus enough to render a
candidate (`phrasing`, `template_section`). The rest of that row shape
belongs to whichever package eventually owns compiling candidates from
engagement documents; this package only re-ranks an already-compiled set.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BankCandidate(BaseModel):
    """One candidate question in a meeting's recompiled bank (PRD FR-4.8, architecture section 3.6).

    `priority` orders candidates within the bank — lower is ranked higher —
    mirroring the ascending `impact_rank` convention `OpenQuestion` already
    uses elsewhere in this codebase (`debrief/pipeline/models.py`).
    `inherited_from_open_question` is `True` only for a candidate
    `recompile_meeting_bank` derived directly from a prior meeting's open
    question rather than from the engagement's own compiled candidate set,
    so a caller can render "carried forward from last time" distinctly from
    a freshly compiled candidate.
    """

    id: str
    template_section: str
    phrasing: str
    priority: int = Field(ge=1)
    inherited_from_open_question: bool = False
    #: The same question at a glance — what the panel renders above the
    #: phrasing and the only tier an operator reads without breaking eye
    #: contact with the client (FR-6.2).
    #:
    #: Part of the slice after all, because the panel reads *this* bank rather
    #: than the engagement's compile: a field this package declined to carry
    #: was a field the panel could never show, however well the compiler
    #: drafted it.
    #:
    #: Empty for an inherited open question, which is prose carried forward
    #: from the last meeting rather than a drafted candidate — nothing ever
    #: shortened it. Kept empty rather than defaulted to the phrasing, so a
    #: caller can tell a question with a short form from one without.
    stub: str = ""


class MeetingQuestionBank(BaseModel):
    """The fresh, per-meeting recompiled question bank (PRD FR-4.8).

    Recomputed by `recompile_meeting_bank` for every meeting rather than
    reused across an engagement's meetings — "the bank" a live meeting reads
    from is always this meeting's own recompile, not the engagement's
    original compile from `POST /api/engagements/{id}/bank/compile`.
    """

    meeting_id: str
    candidates: list[BankCandidate]
    generated_at: datetime
