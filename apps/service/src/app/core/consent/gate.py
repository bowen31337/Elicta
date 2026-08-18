"""Consent gate evaluation (PRD L1/L2): decide whether capture may begin.

This is deliberately independent of any engagement/meeting persistence
model — callers pass in the engagement's configured `ConsentModel` and
whether this meeting already has a recorded confirmation, and get back a
gate result plus (when required) the prompt to show the operator. Recording
the confirmation itself, with timestamp and operator, is a separate concern
handled by `confirmation.py` (PRD feature 246).
"""

from app.core.consent.models import (
    ConsentGate,
    ConsentGateStatus,
    ConsentModel,
    ConsentPrompt,
)

CONSENT_PROMPT = ConsentPrompt(
    title="Recording consent required",
    body=(
        "This meeting will be recorded and transcribed. Continuing confirms "
        "that every participant has been informed and has consented to "
        "being recorded."
    ),
    legal_basis="NSW Surveillance Devices Act — all-party consent (PRD §11, L1/L2)",
)


def evaluate_consent_gate(
    consent_model: ConsentModel,
    *,
    confirmed_this_meeting: bool = False,
) -> ConsentGate:
    """Evaluate whether a meeting may begin capture right now.

    - ``ENGAGEMENT_LEVEL``: consent was already captured for the engagement
      as a whole, so no per-meeting prompt is required.
    - ``PER_MEETING`` and not yet confirmed: capture must not begin until
      the operator confirms the prompt.
    - ``PER_MEETING`` and already confirmed: capture may begin.
    """

    if consent_model is ConsentModel.ENGAGEMENT_LEVEL:
        return ConsentGate(status=ConsentGateStatus.NOT_REQUIRED, prompt=None)

    if confirmed_this_meeting:
        return ConsentGate(status=ConsentGateStatus.CONFIRMED, prompt=None)

    return ConsentGate(
        status=ConsentGateStatus.AWAITING_CONFIRMATION,
        prompt=CONSENT_PROMPT,
    )
