"""Domain types for tagging a compiled candidate with its PRD FR-4.2 tag set and slotted phrasing.

FR-4.2 names exactly four tags every candidate row must carry before it can
enter the `candidate` table (architecture §3.6): target template section,
trigger conditions, priority, and prerequisite candidate ids. `CandidateTags`
is that tag set on its own, decoupled from any one candidate-producing
technique's full row shape (`compiler/agent/models.py`'s `AnalystBankCandidate`,
`compiler/bank/models.py`'s `BankCandidate`, or a future technique's own
shape) -- every one of those already carries these same four fields inline,
but none of them validate `requires` against the batch the candidate actually
ships in. `CandidateTagging` is the local input shape this module accepts
instead of importing any of those: an untyped `id` plus the tag set a
candidate-producing technique proposes, so this module stays usable by
whichever technique compiled the candidate rather than coupled to one.

`CandidateTagging.phrasing` rides along for the same reason architecture §3.6
stores it next to the tags in the same `candidate` row: "`phrasing` ... may
contain `{slot}` placeholders" that the live-meeting runtime later fills by
string interpolation ("`What's the slowest {term} the {function} team would
still accept?`", instantiated from `TriggerEvent.span` and the attendee
roster -- §3.6, ADR-003). This module never fills those placeholders itself;
it only has to make sure a candidate's phrasing is still safe to interpolate
by the time it is persisted.

`TaggedCandidate` is the validated result -- identical fields to
`CandidateTagging`, but only reachable through `tag_candidates`, so a
`TaggedCandidate` is a guarantee its `requires` ids resolve within the same
batch and its `phrasing` placeholders are well-formed and named, rather than
just a hopeful LLM or heuristic output.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateTags(BaseModel):
    """The PRD FR-4.2 tag set: target template section, trigger conditions, priority, and prerequisite ids."""

    template_section: str = Field(min_length=1)
    trigger_types: list[str] = Field(min_length=1)
    priority: int = Field(ge=1)
    requires: list[str] = Field(default_factory=list)


class CandidateTagging(BaseModel):
    """One candidate id and phrasing paired with the FR-4.2 tags a compiling technique proposes, before validation."""

    id: str = Field(min_length=1)
    phrasing: str = Field(min_length=1)
    tags: CandidateTags


class TaggedCandidate(BaseModel):
    """One candidate row's phrasing and FR-4.2 tags, validated against its batch and ready to persist (architecture §3.6).

    `phrasing` is persisted verbatim, `{slot}` placeholders included -- the
    runtime instantiates it by string interpolation, so stripping or
    escaping a placeholder here would silently break that hot path instead
    of the model-free instantiation architecture §3.6 designs around.
    """

    id: str
    phrasing: str
    template_section: str
    trigger_types: list[str]
    priority: int
    requires: list[str]


class CandidateEmbedding(BaseModel):
    """One candidate's embedding vector, keyed by id (PRD FR-4.3, architecture §3.6).

    Mirrors `techniques/authority_matching.py`'s `CandidateAuthorityMatch`: a
    small, decoupled value keyed by `candidate_id` rather than a full
    candidate row, since this module -- like that one -- only ever computes
    and persists its own column (`candidate.embedding`, `BLOB NOT NULL`) and
    has no reason to carry the rest of the row along with it. `embedding`
    must be non-empty: an empty vector would satisfy the column's `NOT NULL`
    constraint while still leaving the row unretrievable, which is the exact
    silent failure FR-4.3 exists to prevent.
    """

    candidate_id: str = Field(min_length=1)
    embedding: bytes = Field(min_length=1)
