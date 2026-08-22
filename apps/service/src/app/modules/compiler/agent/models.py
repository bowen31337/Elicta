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


#: The requirements-template sections a bank is filed under when the engagement
#: has not named a template of its own.
#:
#: A list, and a closed one, because the Analyst pass used to be given neither.
#: Told to "use the sections the documents themselves imply", a live compile
#: invented a section called *Operations* and put 65 of its 97 candidates in it
#: — a bin, not a section. Two banks filed under sections each compile chose
#: for itself cannot be compared, and coverage tracked against sections nobody
#: declared can never be marked covered.
#:
#: Resolving an engagement's own `target_requirements_template` — free text
#: today — into a section list is separate and still open. Until it lands this
#: is the taxonomy, stated once rather than guessed at per compile.
DEFAULT_TEMPLATE_SECTIONS: tuple[str, ...] = (
    "Scope and outcomes",
    "Volumes",
    "Performance",
    "Operations",
    "Integrations",
    "Data and compliance",
    "Roles and decision authority",
    "Constraints and dependencies",
)


class AnalystContextPack(BaseModel):
    """One engagement's compiled context pack, as read by the BMAD Analyst pass (PRD FR-4.1, architecture §3.10)."""

    engagement_id: str = Field(min_length=1)
    sector: str
    project_type: str
    documents: list[ContextPackDocument]
    #: The sections a candidate may be filed under. Empty falls back to
    #: `DEFAULT_TEMPLATE_SECTIONS` at the point the request is built, so an
    #: older caller keeps working and still gets a closed list.
    template_sections: list[str] = Field(default_factory=list)


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


class BmadAnalystBatchSubmissionStatus(str, Enum):
    """Terminal state of one attempt to submit the Analyst pass to the Batch API (architecture §14.4).

    Distinct from `BmadAnalystPassStatus`, which describes a finished pass's
    outcome once its candidates are in hand -- `SUBMITTED` here only means
    the Batch API accepted the workload and handed back a job id; the pass
    itself has no latency constraint (architecture §3.10) and runs to
    completion later, out of this record's view. `FAILED` covers a
    submission attempt that never got a job id at all.
    """

    SUBMITTED = "submitted"
    FAILED = "failed"


class AnalystBatchResult(BaseModel):
    """One request's raw result within a completed Analyst pass batch job, before its engagement is known (architecture §14.4).

    A batch job's results endpoint returns every submitted request's outcome
    in arbitrary order, each carrying back only the `custom_id` the request
    was submitted under -- never its position in the batch -- so `custom_id`
    here is the correlation key a collector must key results by (architecture
    §14.4). This module's convention is to submit each engagement's Analyst
    pass request under its own `engagement_id` as `custom_id`, mirroring
    `EngagementBmadAnalystBatchSubmission`'s one-record-per-engagement shape.
    Exactly one of `output`/`error` is populated, mirroring how a request can
    either succeed or fail independently of every other request sharing its
    batch job.
    """

    custom_id: str = Field(min_length=1)
    output: BmadAnalystPassOutput | None = None
    error: str | None = None


class EngagementBmadAnalystBatchSubmission(BaseModel):
    """Durable record of one attempt to submit an engagement's Analyst pass to the Batch API (architecture §14.4).

    Persisted whether the submission attempt succeeded or failed, mirroring
    `EngagementBmadAnalystPass`: an engagement with no submission record at
    all would be indistinguishable from one that simply hasn't been
    submitted yet, so `status` and `error` make a failed attempt visible
    instead of silent. `batch_job_id` is the vendor-assigned id a later stage
    keys results against by `custom_id`, never by position (architecture
    §14.4) -- it is `None` on a `FAILED` attempt, since no job was ever
    accepted. `requested_at`/`completed_at` bound the submission call itself,
    not the batch run it kicks off -- the Batch API returns a job id
    synchronously; only collecting that job's results is the long-running
    part, and that collection is a separate concern from this one.
    """

    engagement_id: str = Field(min_length=1)
    status: BmadAnalystBatchSubmissionStatus
    engine: str
    batch_job_id: str | None
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
