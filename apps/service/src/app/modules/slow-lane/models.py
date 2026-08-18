"""Domain types for accepting a slow-lane tick over HTTP (PRD FR-5.10; architecture §3.8, §4, §14.3).

`core/crates/slow-lane` owns firing a tick on a fixed cadence and the
"never run two passes at once" overlap invariant, but holds no network
handle itself (see that crate's `lib.rs`/`orchestrator.rs` docs) -- calling
the Messages API for a pass and writing its results back into the bank is
left to whoever consumes its `TickEvent`s. This package is that consumer's
HTTP surface: it accepts one already-decided tick for a meeting and returns
what that pass produced.

`FillState` and `CoverageSlotUpdate` are a local mirror of
`core/crates/coverage`'s `FillState`/`CoverageSlot` (three states, since a
live coverage matrix needs to tell "nothing raised yet" apart from "raised
but not confirmed" per PRD FR-5.6) rather than an import of
`debrief/pipeline/models.py`'s binary `FillState` -- that one describes a
completed debrief classification run, a different, already-finished-meeting
concern from the live matrix a slow-lane pass updates mid-meeting.

`SlowLaneCandidate` is a local mirror of `compiler/bank/models.py`'s
`BankCandidate`, following this codebase's established cross-module
convention (`nudges/models.py`'s `OperatorNudgeDisposition` mirrors
`debrief/session/models.py`'s `NudgeDisposition` the same way) rather than
importing across module boundaries. It omits `inherited_from_open_question`
-- that field distinguishes a candidate carried forward from a prior
meeting's open question, which never applies to a candidate a live
slow-lane pass just generated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FillState(str, Enum):
    """How much of a template section the meeting has covered so far (PRD FR-8.2; architecture §4)."""

    EMPTY = "empty"
    PARTIAL = "partial"
    FILLED = "filled"


class CoverageSlotUpdate(BaseModel):
    """One coverage matrix cell a slow-lane pass updated (architecture §4: `CoverageSlot[]`).

    `satisfied_at` is `None` unless this pass is the one that moved the slot
    to `FILLED` -- mirroring `core/crates/coverage::CoverageStore`'s
    `satisfied_at`, which only a fill transition (not merely remaining
    filled) sets.
    """

    template_section: str
    fill_state: FillState
    satisfied_at: datetime | None = None


class SlowLaneCandidate(BaseModel):
    """One new candidate question a slow-lane pass surfaced (architecture §3.6, §3.8)."""

    id: str
    template_section: str
    phrasing: str
    priority: int = Field(ge=1)


class SlowLaneTickResult(BaseModel):
    """What accepting one slow-lane tick for a meeting produced (PRD FR-5.10).

    `coverage_updates` is empty when the pass changed no slot's fill state,
    and `new_candidates` is empty when it surfaced nothing new -- a tick
    that runs but produces neither is still a 200, not an error: PRD FR-5.10
    and architecture §3.8 make failure non-fatal, and "nothing changed this
    pass" is not a failure.
    """

    meeting_id: str
    coverage_updates: list[CoverageSlotUpdate]
    new_candidates: list[SlowLaneCandidate]
    ticked_at: datetime
