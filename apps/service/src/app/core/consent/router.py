"""HTTP surface for the consent gate and per-meeting consent confirmations.

`build_consent_router` takes lookups and a save callback rather than
reaching into a meeting/engagement persistence layer directly, since that
layer does not live in this package. Whoever wires the app factory (out of
this feature's footprint) supplies the real implementations backed by the
engagement/meeting tables and mounts the returned router.
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from app.core.consent.confirmation import SaveConsentRecord, record_consent_confirmation
from app.core.consent.gate import evaluate_consent_gate
from app.core.consent.models import (
    ConsentConfirmationRequest,
    ConsentGate,
    ConsentModel,
    ConsentRecord,
)

ConsentModelLookup = Callable[[str], Awaitable[ConsentModel]]
ConfirmationLookup = Callable[[str], Awaitable[bool]]


def build_consent_router(
    get_engagement_consent_model: ConsentModelLookup,
    is_confirmed_for_meeting: ConfirmationLookup,
    save_consent_record: SaveConsentRecord,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["consent"])

    @router.get("/{meeting_id}/consent-gate", response_model=ConsentGate)
    async def get_consent_gate(meeting_id: str, engagement_id: str) -> ConsentGate:
        consent_model = await get_engagement_consent_model(engagement_id)
        confirmed = await is_confirmed_for_meeting(meeting_id)
        return evaluate_consent_gate(consent_model, confirmed_this_meeting=confirmed)

    @router.post(
        "/{meeting_id}/consent-confirmation",
        response_model=ConsentRecord,
        status_code=201,
    )
    async def confirm_consent(
        meeting_id: str, payload: ConsentConfirmationRequest
    ) -> ConsentRecord:
        return await record_consent_confirmation(
            meeting_id, payload.confirmed_by, save_consent_record
        )

    return router
