"""HTTP surface for the per-meeting recompiled question bank (PRD FR-4.8).

`build_meeting_bank_router` takes `get_base_candidates` and
`get_inherited_open_questions` as injected callables, mirroring every other
router in this codebase (`engagement/api/router.py`, `debrief/api/router.py`):
no candidate-bank persistence layer lives in this package. Whoever wires the
app factory (out of this feature's footprint) supplies real implementations
-- resolving `meeting_id` to its engagement's compiled candidates, and to the
open questions the engagement's prior meeting raised -- and mounts the
returned router.

`build_bank_candidates_router` follows the same injected-callable shape for
deleting a single candidate before its meeting starts: `delete_candidate` is
whoever wires the app factory's real, persistence-backed implementation, and
raises `CandidateNotFoundError` (same convention as
`engagement/documents/router.py`'s `DocumentNotFoundError`) for an unknown
`candidate_id`, which this router turns into a 404. Its route is scoped to
`/api/bank/candidates/{id}` rather than nested under `/api/meetings`, since a
candidate is deleted by its own id regardless of which meeting's bank it
currently ranks into -- the same `/api/documents/{document_id}` convention
`build_document_status_router` uses instead of nesting under
`/api/engagements`.

`build_bank_candidates_router` also takes an `update_candidate` callback for
editing, reordering, or pruning a candidate before its meeting starts
(`PATCH /api/bank/candidates/{id}`, returns 200 with the updated candidate).
It raises the same `CandidateNotFoundError` as `delete_candidate` for an
unknown `candidate_id`, which this router turns into a 404 the same way.

`build_engagement_bank_router` takes a `get_compiled_candidates` callable,
the same injected-callable shape as the rest of this module, and exposes
`GET /api/engagements/{id}/bank`: an engagement's compiled question bank
rendered as a reviewable tree grouped by `template_section`, rather than
`MeetingQuestionBank`'s flat per-meeting candidate list. Like
`get_meeting_bank`, it always returns 200 -- an engagement with no compiled
candidates yet simply renders an empty tree.

`build_engagement_bank_compile_router` takes a `trigger_bank_compile`
callable and exposes `POST /api/engagements/{id}/bank/compile`: kicking off
the engagement-level compile this package's other modules (`tree.py`,
`recompile.py`) document as their upstream source. Mirrors
`build_replay_start_router`'s (`replay/api/router.py`) shape for starting a
long-running run: `trigger_bank_compile` is a synchronous call that hands
back a job id immediately, the compiling work itself (extraction, tagging,
embedding) runs to completion later out of this router's view, and the
route responds 202 rather than 200 or 201 since nothing has been created
yet at the returned URL -- only accepted for processing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from .errors import CandidateNotFoundError
from .models import (
    BankCandidate,
    BankCompileTrigger,
    CandidatePatchRequest,
    EngagementQuestionBank,
    MeetingQuestionBank,
)
from .recompile import InheritedOpenQuestion, recompile_meeting_bank
from .tree import build_question_bank_tree

GetBaseCandidates = Callable[[str], Awaitable[list[BankCandidate]]]
GetInheritedOpenQuestions = Callable[[str], Awaitable[list[InheritedOpenQuestion]]]
DeleteCandidate = Callable[[str], Awaitable[None]]
UpdateCandidate = Callable[[str, CandidatePatchRequest], Awaitable[BankCandidate]]
GetCompiledCandidates = Callable[[str], Awaitable[list[BankCandidate]]]
TriggerBankCompile = Callable[[str], Awaitable[str]]


def build_meeting_bank_router(
    get_base_candidates: GetBaseCandidates,
    get_inherited_open_questions: GetInheritedOpenQuestions,
) -> APIRouter:
    router = APIRouter(prefix="/api/meetings", tags=["compiler-bank"])

    @router.get("/{meeting_id}/bank", response_model=MeetingQuestionBank, status_code=200)
    async def get_meeting_bank(meeting_id: str) -> MeetingQuestionBank:
        base_candidates = await get_base_candidates(meeting_id)
        inherited_open_questions = await get_inherited_open_questions(meeting_id)
        return recompile_meeting_bank(meeting_id, base_candidates, inherited_open_questions)

    return router


def build_bank_candidates_router(
    delete_candidate: DeleteCandidate,
    update_candidate: UpdateCandidate,
) -> APIRouter:
    router = APIRouter(prefix="/api/bank", tags=["compiler-bank"])

    @router.delete("/candidates/{candidate_id}", status_code=204)
    async def delete_bank_candidate(candidate_id: str) -> None:
        try:
            await delete_candidate(candidate_id)
        except CandidateNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/candidates/{candidate_id}", response_model=BankCandidate, status_code=200)
    async def patch_bank_candidate(
        candidate_id: str, payload: CandidatePatchRequest
    ) -> BankCandidate:
        try:
            return await update_candidate(candidate_id, payload)
        except CandidateNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def build_engagement_bank_router(get_compiled_candidates: GetCompiledCandidates) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["compiler-bank"])

    @router.get("/{engagement_id}/bank", response_model=EngagementQuestionBank, status_code=200)
    async def get_engagement_bank(engagement_id: str) -> EngagementQuestionBank:
        candidates = await get_compiled_candidates(engagement_id)
        return build_question_bank_tree(engagement_id, candidates)

    return router


def build_engagement_bank_compile_router(trigger_bank_compile: TriggerBankCompile) -> APIRouter:
    router = APIRouter(prefix="/api/engagements", tags=["compiler-bank"])

    @router.post("/{engagement_id}/bank/compile", response_model=BankCompileTrigger, status_code=202)
    async def compile_engagement_bank(engagement_id: str) -> BankCompileTrigger:
        job_id = await trigger_bank_compile(engagement_id)
        return BankCompileTrigger(
            job_id=job_id,
            engagement_id=engagement_id,
            triggered_at=datetime.now(UTC),
        )

    return router
