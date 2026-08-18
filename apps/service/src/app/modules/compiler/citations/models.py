"""Domain types for the offline document-extraction and claim-structuring passes (architecture §3.11, §14.4).

Architecture §3.11 ("Native citations, for the compiler") and §14.4 split the
compiler into two calls because document citations are incompatible with
`output_config.format`: "an extraction pass with citations enabled, then a
structuring pass over the extracted claims with the schema applied." This
package is both of those calls -- `extraction.py` runs the first, citations
pass; `structuring.py` runs the second, schema-constrained pass over that
first pass's output. `agent/bmad_analyst.py`'s `AnalystContextPack` models a
*different* structuring pass's input -- a whole context pack's documents as
flat `text`, with no citation grounding -- so this package defines its own
shapes rather than reusing that one: this structuring pass reads the
already-extracted, already-grounded `ExtractedClaim` records this same
package produces, not raw document text.

`CitedSpan` mirrors the shape Claude's Messages API returns for a document
content block with `citations: {enabled: true}` -- `cited_text` plus a
character location -- rather than the vendor response object itself, keeping
this package decoupled from any concrete SDK type per this codebase's
"inject the pass as a callable" convention (`bmad_analyst.py`,
`debrief/pipeline/bmad_analyst.py`).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExtractionSourceDocument(BaseModel):
    """One reference document's full extracted text, as fed into the citations pass (architecture §3.10, §3.11)."""

    document_id: str = Field(min_length=1)
    text: str


class CitedSpan(BaseModel):
    """One character-location citation grounding an extracted claim in its source document (architecture §3.11).

    `start_char_index`/`end_char_index` locate `cited_text` within the named
    document's own `text`, the same `[start, end)` half-open convention
    `debrief/pipeline/citations.py` and `asr-record/citation.py` use for
    their own span types -- so a claim's citation can be checked against the
    source document it names rather than trusted at face value.
    """

    document_id: str = Field(min_length=1)
    cited_text: str = Field(min_length=1)
    start_char_index: int = Field(ge=0)
    end_char_index: int = Field(gt=0)


class ExtractedClaimDraft(BaseModel):
    """One claim as the extraction pass chain returns it, before an id is assigned (architecture §3.11)."""

    text: str = Field(min_length=1)
    citation: CitedSpan


class DocumentExtractionOutput(BaseModel):
    """The raw bundle one document-extraction pass run returns, before claim ids are assigned (architecture §3.11)."""

    claims: list[ExtractedClaimDraft]


class ExtractedClaim(BaseModel):
    """One `ExtractedClaimDraft` with its durable id assigned and its citation validated against the source text."""

    id: str = Field(min_length=1)
    text: str
    citation: CitedSpan


class ExtractionPassStatus(str, Enum):
    """Terminal state of one document-extraction pass run over an engagement's reference documents."""

    COMPLETE = "complete"
    FAILED = "failed"


class EngagementDocumentExtractionPass(BaseModel):
    """Durable record of one document-extraction pass run over an engagement's reference documents (architecture §3.11).

    Persisted whether the run succeeded or failed, mirroring
    `agent/models.py`'s `EngagementBmadAnalystPass` and
    `debrief/pipeline/models.py`'s `SessionCitationTable`: an engagement with
    no pass record at all would be indistinguishable from one that simply
    hasn't been extracted yet. `claims` is `None` on a `FAILED` run.
    """

    engagement_id: str = Field(min_length=1)
    status: ExtractionPassStatus
    claims: list[ExtractedClaim] | None
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class ClaimStructuringDraft(BaseModel):
    """One structured candidate as the schema-constrained structuring pass chain returns it (architecture §14.4, §3.6).

    `claim_id` names which `ExtractedClaim` this candidate was structured
    from -- the chain is never asked for `source_doc` itself, since that
    provenance string is derived deterministically from the named claim's
    already-validated citation (`structuring.py`'s `build_structured_candidates`),
    not trusted at face value the way `agent/models.py`'s `BmadCandidateDraft.source_doc`
    is. The remaining fields mirror `BmadCandidateDraft` one-for-one: they're
    the same `candidate` table columns (architecture §3.6) this pass is
    responsible for filling in given a citation-grounded claim.
    """

    claim_id: str = Field(min_length=1)
    template_section: str = Field(min_length=1)
    trigger_types: list[str] = Field(min_length=1)
    phrasing: str = Field(min_length=1)
    stub: str = Field(min_length=1)
    lang: str = Field(min_length=1)
    priority: int = Field(ge=1)
    requires: list[str] = Field(default_factory=list)
    authority_match: list[str] = Field(default_factory=list)


class ClaimStructuringOutput(BaseModel):
    """The raw bundle one claim-structuring pass run returns, before candidate ids and `source_doc` are assigned."""

    candidates: list[ClaimStructuringDraft]


class StructuredCitationCandidate(BaseModel):
    """One schema-valid candidate record structured from a citation-grounded claim (architecture §14.4, §3.6).

    This is the pre-embedding candidate shape for a claim that went through
    the citations pass -- everything the `candidate` table (architecture
    §3.6) needs except `embedding` and `engagement_id`, mirroring
    `agent/models.py`'s `AnalystBankCandidate`. `source_doc` is never `None`
    here, unlike `AnalystBankCandidate.source_doc`: every candidate this
    package structures traces back to an extracted claim, which always
    carries a validated citation.
    """

    id: str = Field(min_length=1)
    template_section: str
    trigger_types: list[str]
    phrasing: str
    stub: str
    lang: str
    priority: int = Field(ge=1)
    requires: list[str]
    authority_match: list[str]
    source_doc: str = Field(min_length=1)


class ClaimStructuringPassStatus(str, Enum):
    """Terminal state of one claim-structuring pass run over an engagement's extracted claims."""

    COMPLETE = "complete"
    FAILED = "failed"


class EngagementClaimStructuringPass(BaseModel):
    """Durable record of one claim-structuring pass run over an engagement's extracted claims (architecture §14.4).

    Persisted whether the run succeeded or failed, mirroring this package's
    own `EngagementDocumentExtractionPass`: an engagement with no pass
    record at all would be indistinguishable from one that simply hasn't
    been structured yet. `candidates` is `None` on a `FAILED` run.
    """

    engagement_id: str = Field(min_length=1)
    status: ClaimStructuringPassStatus
    candidates: list[StructuredCitationCandidate] | None
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
