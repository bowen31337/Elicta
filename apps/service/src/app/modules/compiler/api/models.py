"""Domain types for the per-meeting recompiled question bank HTTP surface (PRD FR-4.8).

`BankCandidate` is a deliberately small slice of the full compiled-candidate
row shape (architecture section 3.6: template_section, trigger_types,
phrasing, stub, lang, priority, requires, authority_match, source_doc,
embedding) -- this package only needs the fields `recompile.py` reasons about
(`priority`, ordering) plus enough to render a candidate (`phrasing`,
`template_section`). The rest of that row shape belongs to whichever package
owns compiling candidates from engagement documents; this package only
re-ranks an already-compiled set for one meeting.

`CandidatePatchRequest` backs editing, reordering, or pruning a candidate
before its meeting starts (`PATCH /api/bank/candidates/{id}`): all three are
one caller-facing action -- change some subset of a candidate's mutable
fields -- so they share one partial-update request body rather than three
routes. `phrasing` covers editing the question's wording, `priority` covers
reordering it within the bank (same ascending, lower-ranks-higher
convention `BankCandidate.priority` already uses), and `pruned` covers
excluding it from the bank without the hard, unrecoverable removal
`DELETE /api/bank/candidates/{id}` performs. All three are optional so a
caller changes only what it means to -- editing wording shouldn't force a
reorder -- but at least one must be supplied, mirroring
`MeetingUpdateRequest` (`engagement/meetings/models.py`)'s "no-op PATCH"
guard.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BankCandidate(BaseModel):
    """One candidate question in a meeting's recompiled bank (PRD FR-4.8, architecture section 3.6).

    `priority` orders candidates within the bank -- lower is ranked higher --
    mirroring the ascending `impact_rank` convention `OpenQuestion` already
    uses elsewhere in this codebase (`debrief/pipeline/models.py`).
    `inherited_from_open_question` is `True` only for a candidate
    `recompile_meeting_bank` derived directly from a prior meeting's open
    question rather than from the engagement's own compiled candidate set, so
    a caller can render "carried forward from last time" distinctly from a
    freshly compiled candidate. `pruned` is `True` once a caller has excluded
    the candidate from the bank via `PATCH /api/bank/candidates/{id}` --
    whoever supplies `get_base_candidates` (out of this feature's footprint)
    is responsible for leaving pruned candidates out of what it returns, the
    same way it would leave out a hard-deleted one.
    """

    id: str
    template_section: str
    phrasing: str
    priority: int = Field(ge=1)
    inherited_from_open_question: bool = False
    pruned: bool = False


class CandidatePatchRequest(BaseModel):
    """A partial update to one bank candidate: edit its phrasing, reorder its priority, or prune it (PRD FR-4.8).

    All fields are optional so a caller can change just one aspect at a
    time, but at least one must be supplied, since a PATCH with nothing to
    change has no meaningful effect to report as a 200.
    """

    model_config = ConfigDict(extra="forbid")

    phrasing: str | None = Field(default=None, min_length=1)
    priority: int | None = Field(default=None, ge=1)
    pruned: bool | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> CandidatePatchRequest:
        if self.phrasing is None and self.priority is None and self.pruned is None:
            raise ValueError("at least one of phrasing, priority, pruned must be provided")
        return self


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


class QuestionBankSection(BaseModel):
    """One template section's branch in the reviewable question bank tree (PRD FR-4.8).

    `candidates` carries a section's candidates in the same relative order
    they arrived in from the compiled candidate set -- the same ascending,
    lower-ranks-higher `priority` convention `BankCandidate` already uses --
    so a section's order in the tree matches the order a reviewer would rank
    them in.
    """

    template_section: str
    candidates: list[BankCandidate]


class EngagementQuestionBank(BaseModel):
    """An engagement's compiled question bank, rendered as a reviewable tree grouped by template section (PRD FR-4.8).

    Grouped into `sections` rather than returned as `MeetingQuestionBank`'s
    flat candidate list: this is the engagement's own compiled set (from
    `POST /api/engagements/{id}/bank/compile`, out of this feature's
    footprint) as a reviewer inspects it once, before any individual
    meeting recompiles from it -- so it renders as branches a reviewer can
    expand and act on rather than one long list.
    """

    engagement_id: str
    sections: list[QuestionBankSection]
    generated_at: datetime


class BankCompileTrigger(BaseModel):
    """Handle for one engagement's bank compile job, returned immediately on trigger (PRD FR-4.8).

    Returned when `POST /api/engagements/{id}/bank/compile` is accepted,
    before the actual compiling work (extraction, tagging, embedding -- all
    out of this feature's footprint) has produced any candidates yet.
    `job_id` is what a caller polls or correlates against later, mirroring
    `RecordPathTranscriptionJob`'s (`asr-record/models.py`) job-handle
    convention for an accepted, not-yet-finished run.
    """

    job_id: str = Field(min_length=1)
    engagement_id: str
    triggered_at: datetime
