"""HTTP surface for the consent gate and per-meeting consent confirmations.

`build_consent_router` takes lookups and a save callback rather than
reaching into a meeting/engagement persistence layer directly, since that
layer does not live in this package. Whoever wires the app factory (out of
this feature's footprint) supplies the real implementations backed by the
engagement/meeting tables and mounts the returned router.
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

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
ConsentRecordLookup = Callable[[str], Awaitable[ConsentRecord | None]]


def build_consent_router(
    get_engagement_consent_model: ConsentModelLookup,
    is_confirmed_for_meeting: ConfirmationLookup,
    save_consent_record: SaveConsentRecord,
    get_consent_record: ConsentRecordLookup | None = None,
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

    if get_consent_record is not None:

        @router.get(
            "/{meeting_id}/consent-record",
            response_model=ConsentRecord,
            status_code=200,
        )
        async def get_consent_record_endpoint(meeting_id: str) -> ConsentRecord:
            """Who confirmed consent for this meeting, and when.

            The gate answers whether capture may begin; this answers who is
            accountable for it having been disclosed. Both matter, and only
            the first was readable — the confirmation was written to a
            durable record that nothing ever served back, so a screen could
            show that consent was on record but not whose word that was.

            A 404 means nobody has confirmed yet, which is a real and normal
            state before a meeting rather than a fault.
            """

            record = await get_consent_record(meeting_id)
            if record is None:
                raise HTTPException(status_code=404, detail="no consent record")
            return record

    return router
