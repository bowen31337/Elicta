"""HTTP surface for adding to an engagement's vocabulary list (PRD FR-3.6).

`build_vocabulary_router` takes an `add_vocabulary_term` callback rather than
importing the `vocabulary_terms` persistence model directly, since that layer
does not live in this package (`app/modules/engagement/vocabulary`) — same
reasoning as `app/modules/engagement/api/router.py`. Whoever wires the app
factory (out of this feature's footprint) supplies the real,
persistence-backed implementation and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .errors import EngagementNotFoundError
from .schemas import VocabularyTermCreateRequest, VocabularyTermResponse

AddVocabularyTerm = Callable[[str, VocabularyTermCreateRequest], Awaitable[str]]


def build_vocabulary_router(add_vocabulary_term: AddVocabularyTerm) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["engagement-vocabulary"])

    @router.post(
        "/{engagement_id}/vocabulary",
        response_model=VocabularyTermResponse,
        status_code=201,
    )
    async def add_vocabulary_term_endpoint(
        engagement_id: str,
        payload: VocabularyTermCreateRequest,
    ) -> VocabularyTermResponse:
        try:
            term_id = await add_vocabulary_term(engagement_id, payload)
        except EngagementNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return VocabularyTermResponse(
            term_id=term_id,
            engagement_id=engagement_id,
            term=payload.term,
            term_type=payload.term_type,
        )

    return router
