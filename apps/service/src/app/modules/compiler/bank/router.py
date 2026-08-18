"""HTTP surface for the per-meeting recompiled question bank (PRD FR-4.8).

`build_meeting_bank_router` takes `get_base_candidates` and
`get_inherited_open_questions` as injected callables, mirroring every other
router in this codebase (`engagement/api/router.py`,
`debrief/artifacts/router.py`): no candidate-bank persistence layer lives in
this package. Whoever wires the app factory (out of this feature's
footprint) supplies real implementations — resolving `meeting_id` to its
engagement's compiled candidates, and to the open questions the engagement's
prior meeting raised — and mounts the returned router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter

from .models import BankCandidate, MeetingQuestionBank
from .recompile import InheritedOpenQuestion, recompile_meeting_bank

GetBaseCandidates = Callable[[str], Awaitable[list[BankCandidate]]]
GetInheritedOpenQuestions = Callable[[str], Awaitable[list[InheritedOpenQuestion]]]


def build_meeting_bank_router(
    get_base_candidates: GetBaseCandidates,
    get_inherited_open_questions: GetInheritedOpenQuestions,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["compiler-bank"])

    @router.get("/{meeting_id}/bank", response_model=MeetingQuestionBank)
    async def get_meeting_bank(meeting_id: str) -> MeetingQuestionBank:
        base_candidates = await get_base_candidates(meeting_id)
        inherited_open_questions = await get_inherited_open_questions(meeting_id)
        return recompile_meeting_bank(meeting_id, base_candidates, inherited_open_questions)

    return router
