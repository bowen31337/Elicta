"""HTTP surface for the egress audit log (PRD NFR-2.7 / architecture §8,
"single audited chokepoint").

`build_egress_audit_router` takes an `EgressLogQuery` rather than reading
from the `egress_log` table directly, since that storage binding does not
live in this package. Whoever wires the app factory (out of this feature's
footprint) supplies the real, persistence-backed implementation and mounts
the returned router.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.egress.models import EgressLogRow
from app.core.egress.query import EgressLogQuery


def build_egress_audit_router(query_egress_log: EgressLogQuery) -> APIRouter:
    router = APIRouter(prefix="/api/audit", tags=["egress-audit"])

    @router.get("/egress", response_model=list[EgressLogRow])
    async def get_egress_audit_log(
        engagement_id: str,
        start_ms: int = Query(..., ge=0),
        end_ms: int = Query(..., ge=0),
    ) -> list[EgressLogRow]:
        if end_ms < start_ms:
            raise HTTPException(
                status_code=422,
                detail="end_ms must be greater than or equal to start_ms",
            )
        return await query_egress_log.query(engagement_id, start_ms, end_ms)

    return router
