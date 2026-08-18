"""Domain types for the offline document-extraction pass with native citations enabled (architecture §3.11).

Architecture §3.11 ("Native citations, for the compiler") splits the compiler
into two calls because document citations are incompatible with
`output_config.format`: "an extraction pass with citations enabled, then a
structuring pass over the extracted claims with the schema applied." This
package is that first pass. `agent/bmad_analyst.py`'s `AnalystContextPack`
already models the *second* pass's input -- a document's content as flat
`text`, with no citation grounding -- so this package defines its own,
earlier-stage shapes rather than reusing that one: by the time a document
reaches the structuring pass, its claims have already been extracted and
grounded here.

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
