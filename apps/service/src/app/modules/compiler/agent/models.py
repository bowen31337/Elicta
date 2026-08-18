"""Domain types for the offline BMAD Analyst pass over an engagement's context pack (PRD FR-4.1, FR-4.2).

`AnalystContextPack` is a deliberately local input shape rather than an
import of `engagement/index/models.py`'s `ContextPackDigest`: that digest is
the compact, content-free artifact FR-3.3 persists ("compile, don't dump"),
while the Analyst pass itself is the one consumer that still needs to read
this document's actual extracted content (architecture §3.10: "Document
ingestion and chunking, entity and claim extraction, then the BMAD Analyst
pass"). Whoever assembles the real pack for an engagement (out of this
feature's footprint — chunking and extraction already live in
`engagement/index`) is responsible for handing this module that content in
this shape.

`BmadCandidateDraft` mirrors the `candidate` table's schema (architecture
§3.6) for every field the Analyst pass itself can produce -- `template_section`,
`trigger_types`, `phrasing`, `stub`, `lang`, `priority`, `requires`,
`authority_match`, `source_doc` -- but omits `id`, `engagement_id`, and
`embedding`: an id and engagement_id are assigned by this module rather than
the chain (`build_bank_candidates`), and embedding candidates for retrieval
(PRD FR-4.3) is a separate, downstream concern this pass has no reason to
perform itself. Required fields are exactly PRD FR-4.2's tagging contract --
target template section, trigger conditions, priority, and prerequisite
knowledge (`requires`) -- so a chain response missing any of them fails
validation before this module ever has to reason about an incomplete
candidate.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.modules.engagement.documents.models import DocumentStatus


class ContextPackDocument(BaseModel):
    """One reference document's extracted content, as fed into the Analyst pass (PRD FR-3.4, FR-4.1).

    `status` rides along untouched from `engagement/documents/models.py`,
    mirroring `compiler/techniques/models.py`'s `HypothesisDocumentClaim` --
    the same document-status taxonomy governs how the Analyst pass must treat
    a document's claims (ground truth vs. a hypothesis to verify vs.
    superseded background) regardless of which compiling technique reads it.
    """

    document_id: str = Field(min_length=1)
    status: DocumentStatus
    text: str


class AnalystContextPack(BaseModel):
    """One engagement's compiled context pack, as read by the BMAD Analyst pass (PRD FR-4.1, architecture §3.10)."""

    engagement_id: str = Field(min_length=1)
    sector: str
    project_type: str
    documents: list[ContextPackDocument]


class BmadCandidateDraft(BaseModel):
    """One candidate question as the Analyst pass chain returns it, before an id is assigned (PRD FR-4.1, FR-4.2).

    `trigger_types` names which live-trigger conditions (PRD FR-5) this
    candidate answers, and `requires` names prerequisite candidate ids this
    candidate depends on -- both required and non-empty-by-construction only
    for `trigger_types` (a candidate with no trigger type could never be
    selected at runtime); `requires` and `authority_match` default to empty
    since most candidates have no prerequisite and no specific authority
    requirement.
    """

    template_section: str = Field(min_length=1)
    trigger_types: list[str] = Field(min_length=1)
    phrasing: str = Field(min_length=1)
    stub: str = Field(min_length=1)
    lang: str = Field(min_length=1)
    priority: int = Field(ge=1)
    requires: list[str] = Field(default_factory=list)
    authority_match: list[str] = Field(default_factory=list)
    source_doc: str | None = None


class BmadAnalystPassOutput(BaseModel):
    """The raw bundle one BMAD Analyst pass run returns, before candidate ids are assigned (PRD FR-4.1)."""

    candidates: list[BmadCandidateDraft]


class AnalystBankCandidate(BaseModel):
    """One `BmadCandidateDraft` with its durable id and engagement assigned (PRD FR-4.1, FR-4.2, architecture §3.6).

    This is the pre-embedding candidate shape: everything the `candidate`
    table (architecture §3.6) needs except `embedding`, which is assigned
    when this pass's output is embedded for retrieval (PRD FR-4.3, out of
    this feature's footprint).
    """

    id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    template_section: str
    trigger_types: list[str]
    phrasing: str
    stub: str
    lang: str
    priority: int = Field(ge=1)
    requires: list[str]
    authority_match: list[str]
    source_doc: str | None = None


class BmadAnalystPassStatus(str, Enum):
    """Terminal state of one BMAD Analyst pass run over an engagement's context pack."""

    COMPLETE = "complete"
    FAILED = "failed"


class EngagementBmadAnalystPass(BaseModel):
    """Durable record of one BMAD Analyst pass run over an engagement's context pack (PRD FR-4.1).

    Persisted whether the run succeeded or failed, mirroring
    `debrief/pipeline/models.py`'s `SessionBmadAnalystChain`: an engagement
    with no pass record at all would be indistinguishable from one that
    simply hasn't been compiled yet, so `status` and `error` make a failed
    run visible instead of silent. `candidates` is `None` on a `FAILED` run.
    """

    engagement_id: str = Field(min_length=1)
    status: BmadAnalystPassStatus
    engine: str
    candidates: list[AnalystBankCandidate] | None
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
