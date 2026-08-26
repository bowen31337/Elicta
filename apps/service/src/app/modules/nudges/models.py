"""Domain types for recording an operator's disposition of a surfaced nudge (PRD FR-6.6/6.7).

`OperatorNudgeDisposition` is a local mirror of `debrief/session/models.py`'s
`NudgeDisposition` rather than an import of it, following this codebase's
established convention (`engagement/meetings/models.py`'s `EngagementContext`
mirrors `engagement/api`'s engagement fields the same way): the debrief
package's enum describes how a nudge was resolved *by the time the call
ended*, a read-side concern for a package that lives elsewhere, while this
one describes what an operator explicitly did with a nudge while it was
still live. It deliberately excludes `debrief`'s `FIRED` member: `FIRED`
means a nudge surfaced and nothing happened to it before the call ended --
that is the absence of an operator disposition, not one an operator ever
submits through this endpoint.

`TAKEN` corresponds to the operator tapping `Asked it` (PRD FR-6.6/6.7);
`PARKED` corresponds to tapping `Park it`. Both are tap-only actions with no
free-text component, matching the rest of the primary input's chips.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class OperatorNudgeDisposition(str, Enum):
    """What an operator explicitly did with a surfaced nudge (PRD FR-6.6/6.7)."""

    TAKEN = "taken"
    PARKED = "parked"


class NudgeDispositionRequest(BaseModel):
    """Request body for recording an operator's disposition of one nudge."""

    model_config = ConfigDict(extra="forbid")

    disposition: OperatorNudgeDisposition


class NudgeDispositionResponse(BaseModel):
    """A recorded operator disposition, echoed back for confirmation."""

    meeting_id: str
    nudge_id: str
    disposition: OperatorNudgeDisposition
    recorded_at: datetime


class SurfacedNudge(BaseModel):
    """One nudge a meeting put in front of the operator, and its fate.

    Durable because the panel's history is the operator's only route back to
    a question they have not dealt with, and because `Park it` and `Go
    deeper` address a thread by id alone — held in memory, a restart left the
    service unable to say which meeting had raised any of them.

    `term` and `category` are nullable for the question an operator typed:
    the escape hatch produces a real nudge with no trigger behind it.
    `candidate_id` is nullable for a templated one, where the bank had
    nothing to offer. `disposition` is null until they answer, which is a
    third state rather than a default — a nudge nobody got to is not one that
    was ignored.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    meeting_id: str
    stub: str
    question: str
    trigger_reason: str
    created_at: datetime
    term: str | None = None
    category: str | None = None
    candidate_id: str | None = None
    disposition: OperatorNudgeDisposition | None = None
