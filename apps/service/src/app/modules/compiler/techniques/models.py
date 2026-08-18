"""Domain types for compiling techniques (PRD FR-4.6, FR-4.9).

`HypothesisDocumentClaim` is a deliberately local input shape: no document
claim-extraction pipeline exists yet in this codebase. The closest existing
concept, `ReferenceClaim` (`engagement/state/models.py`), covers a different
feature — FR-3.12's context-pack claims a user manually flags to verify —
and isn't tied to a `document_id` or a `DocumentStatus`. Whoever extracts
real claims from a hypothesis-tagged document's content (out of this
feature's footprint) is responsible for handing them to
`generate_verification_questions` in this shape.

`document_status` reuses `DocumentStatus` from
`engagement/documents/models.py` directly rather than a locally decoupled
enum: that module's own docstring already narrates this exact downstream
behaviour ("hypothesis documents generate verification questions instead"
of being treated as fact), so this technique firing only on
`DocumentStatus.HYPOTHESIS` is the intended coupling, not incidental.

`EngagementStage` and `CandidateShape` back `stage_suppression.py` (PRD
FR-4.6). Neither an engagement-stage lifecycle nor a problem/solution/epic
candidate taxonomy exists elsewhere in this codebase yet, so both are
net-new local concepts rather than reuses of an existing enum.
`ShapedCandidate` is the local input shape pairing an already-compiled
`BankCandidate` with its shape tag: whoever classifies a candidate's shape
(out of this feature's footprint — presumably the BMAD analyst pass from
FR-4.1/FR-4.2 that assigns each candidate's target template section) is
responsible for handing them to `suppress_out_of_stage_candidates` in this
shape.

`CandidateAuthorityRequirement` backs `authority_matching.py` (PRD FR-4.7).
It names the same compiled `authority_match` tag the `candidate` table
already carries (architecture §3.6: "roles that can answer this",
`compiler/agent/models.py`'s `BmadCandidateDraft.authority_match`) under a
local field name -- `required_authority` -- so it is never confused with
that module's own computed `authority_match` value. Whoever compiles that
tag (out of this feature's footprint) is responsible for handing it to
`compute_candidate_authority_match` in this shape, the same handoff
`HypothesisDocumentClaim` and `ShapedCandidate` already describe for their
own techniques.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.modules.engagement.documents.models import DocumentStatus

from ..bank.models import BankCandidate


class HypothesisDocumentClaim(BaseModel):
    """One claim attributed to a reference document, tagged with that document's status (PRD FR-4.9)."""

    document_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    document_status: DocumentStatus


class EngagementStage(str, Enum):
    """Which stage an engagement has reached (PRD FR-4.6).

    `DISCOVERY` is the only stage `stage_suppression.py` treats specially:
    it's the stage FR-4.6 requires banks to stay in problem space for.
    `REQUIREMENTS` marks the point the requirements template starts calling
    for solution- and epic-shaped questions, per FR-4.6's own wording.
    """

    DISCOVERY = "discovery"
    REQUIREMENTS = "requirements"


class CandidateShape(str, Enum):
    """Where a compiled candidate sits relative to problem/solution space (PRD FR-4.6).

    `PROBLEM` candidates explore the problem space and are always in scope.
    `SOLUTION` and `EPIC` candidates presuppose a solution direction or
    a delivery-sized unit of work respectively — exactly what FR-4.6 says a
    discovery-stage bank must not surface yet.
    """

    PROBLEM = "problem"
    SOLUTION = "solution"
    EPIC = "epic"


class ShapedCandidate(BaseModel):
    """An already-compiled `BankCandidate` paired with its problem/solution/epic shape tag (PRD FR-4.6)."""

    candidate: BankCandidate
    shape: CandidateShape


class CandidateAuthorityRequirement(BaseModel):
    """One candidate's compiled `authority_match` tag -- the roles that can answer it (PRD FR-4.7, architecture §3.6)."""

    candidate_id: str = Field(min_length=1)
    required_authority: list[str] = Field(default_factory=list)
