"""Domain types for the per-meeting consent gate (PRD L1/L2, D3)."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ConsentModel(str, Enum):
    """How an engagement captures all-party consent (PRD D3).

    ``PER_MEETING`` announces and logs consent fresh at the start of every
    meeting. ``ENGAGEMENT_LEVEL`` captures it once for the whole engagement,
    so individual meetings do not interrupt capture with a prompt.
    """

    PER_MEETING = "per_meeting"
    ENGAGEMENT_LEVEL = "engagement_level"


class ConsentGateStatus(str, Enum):
    """Where a given meeting sits relative to the consent gate."""

    NOT_REQUIRED = "not_required"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"


class ConsentPrompt(BaseModel):
    """Operator-facing copy shown before capture begins (PRD L2)."""

    title: str
    body: str
    legal_basis: str


class ConsentGate(BaseModel):
    """Result of evaluating whether a meeting may begin capture.

    ``capture_may_begin`` is the single field a capture-start flow needs to
    check. ``prompt`` is populated only when the operator must confirm
    consent before capture is allowed to proceed.
    """

    status: ConsentGateStatus
    prompt: ConsentPrompt | None = None

    @property
    def capture_may_begin(self) -> bool:
        return self.status != ConsentGateStatus.AWAITING_CONFIRMATION


class ConsentConfirmationRequest(BaseModel):
    """Payload for an operator confirming the consent prompt (PRD feature 246)."""

    confirmed_by: str = Field(min_length=1)


class ConsentRecord(BaseModel):
    """Durable proof that consent was confirmed for one meeting (PRD feature 246).

    ``confirmed_by`` identifies the operator who confirmed the prompt, not
    the meeting participants — this records accountability for having
    disclosed and confirmed consent, which is what a later audit needs.
    """

    meeting_id: str
    confirmed_by: str
    confirmed_at: datetime
