"""Validates and persists the PRD FR-4.2 tag set for a batch of compiled candidates.

`tag_candidates` is the one place `requires` (prerequisite candidate ids) is
checked against the batch it actually ships in: architecture §3.7 says
"candidates whose `requires` prerequisites are unsatisfied are filtered
before scoring" at *retrieval* time, but nothing upstream of persistence
today checks that a prerequisite id refers to a real candidate at all --
`compiler/agent/models.py`'s `BmadCandidateDraft.requires` accepts whatever
the chain returns, unchecked. A prerequisite id that never resolves within
its own batch would sit in the `candidate` table as a row that can never be
satisfied and so can never be selected, silently and permanently. This
module rejects that batch instead of persisting a candidate no one can ever
reach, and (mirroring FR-4.2's own "prerequisite knowledge" framing, and the
retrieval-time deadlock a self-reference would create) rejects a candidate
naming itself as its own prerequisite the same way.

`persist_candidate_tags` takes the save step as an injected callable rather
than importing a concrete store, mirroring `compiler/agent/bmad_analyst.py`'s
`SaveEngagementBmadAnalystPass`: no durable store exists yet in this
codebase, and this module stays decoupled from any concrete one. Whoever
wires the real `candidate` table (architecture §3.6, out of this feature's
footprint) supplies the real `save`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .models import CandidateTagging, TaggedCandidate

SaveTaggedCandidate = Callable[[TaggedCandidate], Awaitable[None]]


def tag_candidates(taggings: list[CandidateTagging]) -> list[TaggedCandidate]:
    """Validate `taggings` as one batch and return each candidate's tagged row.

    Every `requires` id across the batch must both name another candidate in
    `taggings` and not be the candidate's own id -- either violation raises
    `ValueError` naming the offending candidate and prerequisite id, so a bad
    batch fails before any row is persisted rather than partway through.
    """

    known_ids = {tagging.id for tagging in taggings}

    for tagging in taggings:
        for prerequisite_id in tagging.tags.requires:
            if prerequisite_id == tagging.id:
                raise ValueError(
                    f"candidate {tagging.id!r} names itself as its own prerequisite"
                )
            if prerequisite_id not in known_ids:
                raise ValueError(
                    f"candidate {tagging.id!r} requires unknown prerequisite candidate id {prerequisite_id!r}"
                )

    return [
        TaggedCandidate(
            id=tagging.id,
            template_section=tagging.tags.template_section,
            trigger_types=tagging.tags.trigger_types,
            priority=tagging.tags.priority,
            requires=tagging.tags.requires,
        )
        for tagging in taggings
    ]


async def persist_candidate_tags(
    taggings: list[CandidateTagging], save: SaveTaggedCandidate
) -> list[TaggedCandidate]:
    """Validate `taggings` as one batch via `tag_candidates`, then persist each resulting row through `save`.

    Validation runs over the whole batch before any row is saved, so a
    referential-integrity failure anywhere in the batch leaves nothing
    partially persisted.
    """

    tagged = tag_candidates(taggings)
    for candidate in tagged:
        await save(candidate)
    return tagged
