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

`ElicitationTechnique`, `ElicitationTechniqueSet`, `TechniqueDrawnCandidate`,
`VerifiedTechniqueCandidate`, and `TechniqueVerificationResult` back
`elicitation_technique_set.py` (PRD FR-4.4). None of them reuse an existing
shape: no versioned technique catalogue exists anywhere else in this
codebase, and `BmadCandidateDraft` (`compiler/agent/models.py`, out of this
feature's footprint) has no `technique_id` field to reuse -- that draft
shape is the BMAD Analyst chain's own contract (PRD FR-4.1, FR-4.2) and
adding a field to it is that module's call to make, not this one's.
`TechniqueDrawnCandidate` is therefore the local input shape pairing an
already-compiled `BankCandidate` with the `technique_id` its producer
claims drew it, mirroring `ShapedCandidate`'s candidate-plus-tag pairing;
whoever runs the Analyst chain against the loaded technique set (out of
this feature's footprint) is responsible for handing this module its
output in that shape, the same handoff `ShapedCandidate` and
`CandidateAuthorityRequirement` already describe for their own techniques.
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


class ElicitationTechnique(BaseModel):
    """One named strategy in the elicitation technique set (PRD FR-4.4, architecture §3.11).

    `strategy` is the technique's own instructions -- e.g. a Five Whys or
    SWOT prompt fragment -- as authored in its Agent Skill file, not a
    rendering of any one candidate it goes on to produce.
    """

    technique_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    strategy: str = Field(min_length=1)


class ElicitationTechniqueSet(BaseModel):
    """The full technique set loaded from its Agent Skill directory at one version (PRD FR-4.4).

    `version` names the Agent Skill's own revision (architecture §3.11:
    "versioned, filesystem-backed, editable without a redeploy") -- a
    delivery lead editing the skill's files and bumping this value is the
    entire mechanism by which elicitation strategy changes reach a running
    service.
    """

    version: str = Field(min_length=1)
    techniques: list[ElicitationTechnique]


class TechniqueDrawnCandidate(BaseModel):
    """An already-compiled `BankCandidate` paired with the `technique_id` its producer claims drew it (PRD FR-4.4)."""

    candidate: BankCandidate
    technique_id: str = Field(min_length=1)


class VerifiedTechniqueCandidate(BaseModel):
    """A `TechniqueDrawnCandidate` whose `technique_id` was confirmed present in the current versioned technique set (PRD FR-4.4).

    `technique_version` is that confirming set's own `version`, so a
    persisted candidate names not just which technique produced it but
    which revision of the technique set was live when it was verified.
    """

    candidate: BankCandidate
    technique_id: str = Field(min_length=1)
    technique_version: str = Field(min_length=1)


class TechniqueVerificationResult(BaseModel):
    """The candidates whose technique provenance checked out, plus how many did not (PRD FR-4.4).

    Mirrors `StageSuppressionResult`'s keep-and-count shape: a candidate
    naming a `technique_id` no longer in the live set -- e.g. one a delivery
    lead just renamed or deleted from the skill -- is dropped rather than
    persisted with a dangling reference, and `unknown_technique_count` makes
    that drop visible instead of silently shrinking the bank.
    """

    candidates: list[VerifiedTechniqueCandidate]
    unknown_technique_count: int = Field(ge=0)
