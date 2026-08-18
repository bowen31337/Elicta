"""Scores each candidate's authority_match value against a meeting's attendee roster (PRD FR-4.7).

FR-4.7 asks the ranking function itself to "weight candidate ranking by
attendee decision authority and domain -- surface questions the people
actually in the room can answer." Architecture §3.7's ranking formula scores
this as `w₃·authority_match` ("can someone in this room answer it?") -- a
per-candidate value distinct from the compiled `authority_match` tag
(§3.6: "roles that can answer this") a candidate already carries. That tag
is *who could* answer, static from compile time (`compiler/agent/models.py`'s
`BmadCandidateDraft.authority_match`, out of this feature's footprint,
renamed `required_authority` locally in `.models.CandidateAuthorityRequirement`
so the two are never confused); this module's `authority_match` is *whether
the room can*, computed against one meeting's actual attendee roster and
persisted per candidate so ranking reads a plain number rather than
re-deriving it from the roster on every score.

`Attendee` is reused directly from `engagement/meetings/models.py` rather
than a locally decoupled shape: FR-3.10's structured attendee profile
(`role`, `business_function`, `decision_authority`, `domain_expertise`)
already is the authority-and-domain taxonomy FR-4.7 names, mirroring how
`hypothesis_verification.py` reuses `DocumentStatus` directly rather than
inventing a parallel enum.

A required-authority string matches an attendee when it equals (case-
insensitively) that attendee's `role`, `business_function`,
`decision_authority`, or any one of their `domain_expertise` entries -- the
same four structured fields FR-3.10 captures, so this match never reasons
about free text a candidate or attendee record was never allowed to carry.
`compute_candidate_authority_match` returns the fraction of a candidate's
required-authority tags matched by at least one attendee: a candidate with
no requirement is universally answerable (`1.0`, nobody in particular is
needed); a candidate with requirements and no attendee covering any of them
scores `0.0`; a candidate whose requirements are partially covered scores
proportionally, so ranking can distinguish "half the room can help with
this" from "nobody can."

`persist_candidate_authority_matches` takes the save step as an injected
callable rather than importing a concrete store, mirroring
`tagging/tag_candidates.py`'s `persist_candidate_tags`: no durable store for
the `candidate` table exists yet in this codebase, and this module stays
decoupled from any concrete one. Whoever wires the real table (architecture
§3.6, out of this feature's footprint) supplies the real `save`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from app.modules.engagement.meetings.models import Attendee

from .models import CandidateAuthorityRequirement


class CandidateAuthorityMatch(BaseModel):
    """One candidate's computed authority_match value against a meeting's attendee roster (PRD FR-4.7, architecture §3.7)."""

    candidate_id: str
    authority_match: float = Field(ge=0.0, le=1.0)


SaveCandidateAuthorityMatch = Callable[[CandidateAuthorityMatch], Awaitable[None]]


def _attendee_satisfies(attendee: Attendee, required_authority: str) -> bool:
    target = required_authority.strip().casefold()
    structured_values = [attendee.role, attendee.business_function, attendee.decision_authority]
    if any(value is not None and value.strip().casefold() == target for value in structured_values):
        return True
    return any(expertise.strip().casefold() == target for expertise in attendee.domain_expertise)


def compute_candidate_authority_match(required_authority: list[str], attendees: list[Attendee]) -> float:
    """Score how much of `required_authority` at least one attendee in `attendees` covers (PRD FR-4.7).

    Returns `1.0` when `required_authority` is empty -- a candidate with no
    specific authority requirement is answerable by anyone in the room.
    Otherwise returns the fraction of `required_authority` entries matched by
    at least one attendee's `role`, `business_function`, `decision_authority`,
    or `domain_expertise` (PRD FR-3.10), so a fully covered requirement
    scores `1.0`, a fully uncovered one scores `0.0`, and a partially covered
    one scores proportionally.
    """

    if not required_authority:
        return 1.0

    matched = sum(
        1
        for authority in required_authority
        if any(_attendee_satisfies(attendee, authority) for attendee in attendees)
    )
    return matched / len(required_authority)


def compute_bank_authority_matches(
    requirements: list[CandidateAuthorityRequirement], attendees: list[Attendee]
) -> list[CandidateAuthorityMatch]:
    """Compute one `CandidateAuthorityMatch` per candidate requirement, each scored against the same attendee roster."""

    return [
        CandidateAuthorityMatch(
            candidate_id=requirement.candidate_id,
            authority_match=compute_candidate_authority_match(requirement.required_authority, attendees),
        )
        for requirement in requirements
    ]


async def persist_candidate_authority_matches(
    requirements: list[CandidateAuthorityRequirement],
    attendees: list[Attendee],
    save: SaveCandidateAuthorityMatch,
) -> list[CandidateAuthorityMatch]:
    """Compute authority_match values via `compute_bank_authority_matches`, then persist each one through `save`.

    Mirrors `tagging/tag_candidates.py`'s `persist_candidate_tags`: every
    value is computed before any row is saved, and each is persisted in the
    order `requirements` was given.
    """

    matches = compute_bank_authority_matches(requirements, attendees)
    for match in matches:
        await save(match)
    return matches
