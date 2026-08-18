"""HTTP surface for the consent gate.

`build_consent_router` takes two lookups rather than reaching into a
meeting/engagement persistence layer directly, since that layer does not
live in this package. Whoever wires the app factory (out of this feature's
footprint) supplies the real lookups backed by the engagement/meeting
tables and mounts the returned router.
"""

from collections.abc import Awaitable, Callable

from app.core.consent.gate import evaluate_consent_gate
from app.core.consent.models import ConsentGate, ConsentModel
from fastapi import APIRouter

ConsentModelLookup = Callable[[str], Awaitable[ConsentModel]]
ConfirmationLookup = Callable[[str], Awaitable[bool]]


def build_consent_router(
    get_engagement_consent_model: ConsentModelLookup,
    is_confirmed_for_meeting: ConfirmationLookup,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["consent"])

    @router.get("/{meeting_id}/consent-gate", response_model=ConsentGate)
    async def get_consent_gate(meeting_id: str, engagement_id: str) -> ConsentGate:
        consent_model = await get_engagement_consent_model(engagement_id)
        confirmed = await is_confirmed_for_meeting(meeting_id)
        return evaluate_consent_gate(consent_model, confirmed_this_meeting=confirmed)

    return router
