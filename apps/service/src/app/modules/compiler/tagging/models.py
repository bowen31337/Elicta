"""Domain types for tagging a compiled candidate with its PRD FR-4.2 tag set.

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

`TaggedCandidate` is the validated result -- identical fields to
`CandidateTagging`, but only reachable through `tag_candidates`, so a
`TaggedCandidate` is a guarantee its `requires` ids resolve within the same
batch rather than just a hopeful LLM or heuristic output.
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
    """One candidate id paired with the FR-4.2 tags a compiling technique proposes for it, before validation."""

    id: str = Field(min_length=1)
    tags: CandidateTags


class TaggedCandidate(BaseModel):
    """One candidate row's FR-4.2 tags, validated against its batch and ready to persist (architecture §3.6)."""

    id: str
    template_section: str
    trigger_types: list[str]
    priority: int
    requires: list[str]
