"""Domain types for the requirements coverage matrix artifact (PRD FR-8.2).

`run_section_classification` in `debrief/pipeline/classification.py` already
derives one `CoverageSlotState` per `TemplateSection` in the BMAD taxonomy for
a single classification run, with a `fill_state` of `FILLED` or `EMPTY` and
the utterance_ids that filled it. This package turns that per-run result into
the coverage matrix itself: the durable artifact PRD FR-8 asks for, with
every `FILLED` slot grounded in a record-path citation (PRD FR-2.7/FR-8.7)
rather than left as a bare utterance_id list.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.modules.debrief.pipeline.models import DecisionLogEntry, FillState


class CoverageMatrixStatus(str, Enum):
    """Terminal state of one attempt to build a session's requirements coverage matrix."""

    COMPLETE = "complete"
    FAILED = "failed"


class CoverageCitation(BaseModel):
    """One record-path source reference grounding a filled coverage slot (PRD FR-2.7/FR-8.7).

    Shaped like `asr-record`'s `RecordPathSourceReference`, but defined here
    rather than imported from it: this package stays decoupled from
    `asr-record`'s internals the same way `debrief/pipeline` does, taking the
    actual citation lookup as an injected callable (`CiteFilledSlot` in
    `matrix.py`) instead of importing a concrete transcript type.
    """

    session_id: str
    engine: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    quoted_text: str
    transcript_completed_at: datetime


class CoverageMatrixEntry(BaseModel):
    """One BMAD taxonomy section's row in the requirements coverage matrix (PRD FR-8.2).

    Mirrors the `CoverageSlotState` a classification run produced for this
    section, plus the citation(s) that ground it. `citations` is empty for an
    `EMPTY` slot — there is nothing to cite yet — and carries one grounding
    citation for a `FILLED` slot, spanning the utterances that filled it.
    """

    section_key: str
    title: str
    fill_state: FillState
    utterance_ids: list[str]
    citations: list[CoverageCitation]


class RequirementsCoverageMatrix(BaseModel):
    """Durable requirements coverage matrix artifact for one session (PRD FR-8.2).

    Persisted whether the build succeeded or failed, mirroring every stage in
    `debrief/pipeline`: a session with no matrix at all would be
    indistinguishable from one that simply hasn't had a matrix built yet, so
    `status` and `error` make a failed build visible instead of silent.
    `entries` is empty on a `FAILED` build. `is_fully_covered` is `True` only
    once every entry's `fill_state` is `FILLED` — the single field a caller
    needs to decide whether the session still has open requirements gaps
    against the BMAD taxonomy, without re-scanning every entry itself.
    """

    session_id: str
    status: CoverageMatrixStatus
    entries: list[CoverageMatrixEntry]
    is_fully_covered: bool
    generated_at: datetime
    error: str | None = None


class CoverageGapSection(BaseModel):
    """One BMAD taxonomy section no meeting in an engagement has filled yet (PRD FR-8.10)."""

    section_key: str
    title: str


class EngagementCoverageSummary(BaseModel):
    """Aggregate requirements coverage across every meeting in an engagement (PRD FR-8.10).

    A section counts as covered once *any* of the engagement's meetings has
    filled it in its own `RequirementsCoverageMatrix` — coverage accumulates
    across meetings rather than requiring a single meeting to cover the whole
    taxonomy alone, matching FR-8.10's premise that one discovery call does
    not contain a PRD but a sufficiently covered engagement does.
    `coverage_ratio` is the number `require_prd_generation_coverage` checks
    against the FR-8.10 threshold; `missing_sections` is what its refusal
    message is built from.
    """

    meeting_count: int = Field(ge=0)
    total_sections: int = Field(ge=0)
    covered_sections: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    missing_sections: list[CoverageGapSection]


class ConfirmedRequirement(BaseModel):
    """One BMAD taxonomy section an engagement's standing requirements state treats as confirmed (PRD FR-8.9).

    Sourced only from a `FILLED` `CoverageMatrixEntry` of a `COMPLETE`
    `RequirementsCoverageMatrix` — never from the chain's own account of what
    it discussed — so `citations` always carries at least one grounding
    citation, the same grounding-in-persisted-data reasoning `matrix.py` uses
    for a filled coverage slot.
    """

    section_key: str
    title: str
    citations: list[CoverageCitation]


class RequirementsContradiction(BaseModel):
    """One section a later meeting confirmed differently than the standing requirements state already had it (PRD FR-8.9).

    `merge_requirements_state_forward` in `state.py` raises this whenever a
    meeting's confirmation of `section_key` quotes something other than the
    citation already on record for it — the state merge does not silently let
    the newer meeting overwrite the earlier one, it keeps both citations
    visible as a contradiction the operator can resolve.
    """

    section_key: str
    previous_citation: CoverageCitation
    new_citation: CoverageCitation


class RequirementsState(BaseModel):
    """Durable, engagement-scoped standing requirements state carried forward across meetings (PRD FR-8.9).

    Unlike every other artifact in this package, this is not scoped to one
    session/meeting: there is exactly one `RequirementsState` per engagement,
    upserted by `merge_requirements_state_forward` each time a meeting's
    debrief pipeline completes, so the next meeting in the engagement always
    reads the latest merged state rather than starting from nothing (PRD G4).
    """

    engagement_id: str
    confirmed_requirements: list[ConfirmedRequirement]
    contradictions: list[RequirementsContradiction]
    decisions: list[DecisionLogEntry]
    updated_at: datetime
