"""Domain types for an engagement's reference claims (PRD FR-3.12).

A reference claim is one assertion surfaced from an engagement's context
pack — background material gathered about the client ahead of a session
(PRD FR-3.1 covers the engagement-level background this pack builds on).
`verify_with_client` marks a claim the user isn't confident enough in to
treat as settled: something to actually confirm with the client during this
session rather than carry forward silently as fact.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReferenceClaim(BaseModel):
    """One context-pack assertion for an engagement, with its verify-with-client flag (PRD FR-3.12).

    `claim_id` is scoped to `engagement_id`, not globally unique on its own —
    two different engagements may each have a claim with the same
    `claim_id`. `verify_with_client` defaults to `False`: a claim starts out
    treated as settled background, and only becomes something to confirm
    live once a user explicitly marks it.
    """

    claim_id: str = Field(min_length=1)
    engagement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    verify_with_client: bool = False
