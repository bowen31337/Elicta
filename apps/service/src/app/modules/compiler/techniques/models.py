"""Domain types for the hypothesis-verification compiling technique (PRD FR-4.9).

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
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.engagement.documents.models import DocumentStatus


class HypothesisDocumentClaim(BaseModel):
    """One claim attributed to a reference document, tagged with that document's status (PRD FR-4.9)."""

    document_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    document_status: DocumentStatus
