"""Compiler API package: the per-meeting recompiled question bank (PRD FR-4.8).

Exposes no mounted router -- `build_meeting_bank_router` needs
`get_base_candidates` and `get_inherited_open_questions` injected first, and
`build_bank_candidates_router` needs `delete_candidate` and
`update_candidate` injected first -- so this package is consumed directly by
whoever wires the app factory. `GET /api/meetings/{meeting_id}/bank` always
returns 200: a meeting with no compiled candidates and no inherited open
questions simply gets back an empty `candidates` list rather than a 404,
since a per-meeting bank has no "not found" state the way a single
persisted row does. `DELETE /api/bank/candidates/{id}` returns 204, or 404
if `delete_candidate` raises `CandidateNotFoundError`. `PATCH
/api/bank/candidates/{id}` edits, reorders, or prunes a candidate and
returns 200 with the updated candidate, or 404 if `update_candidate` raises
the same `CandidateNotFoundError`. `GET /api/engagements/{id}/bank` returns
200 with the engagement's compiled question bank rendered as a reviewable
tree grouped by `template_section`.
"""

from __future__ import annotations

from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.models import (
    BankCandidate,
    CandidatePatchRequest,
    EngagementQuestionBank,
    MeetingQuestionBank,
    QuestionBankSection,
)
from app.modules.compiler.api.recompile import (
    INHERITED_TEMPLATE_SECTION,
    InheritedOpenQuestion,
    recompile_meeting_bank,
)
from app.modules.compiler.api.router import (
    DeleteCandidate,
    GetBaseCandidates,
    GetCompiledCandidates,
    GetInheritedOpenQuestions,
    UpdateCandidate,
    build_bank_candidates_router,
    build_engagement_bank_router,
    build_meeting_bank_router,
)
from app.modules.compiler.api.tree import build_question_bank_tree

__all__ = [
    "INHERITED_TEMPLATE_SECTION",
    "BankCandidate",
    "CandidateNotFoundError",
    "CandidatePatchRequest",
    "DeleteCandidate",
    "EngagementQuestionBank",
    "GetBaseCandidates",
    "GetCompiledCandidates",
    "GetInheritedOpenQuestions",
    "InheritedOpenQuestion",
    "MeetingQuestionBank",
    "QuestionBankSection",
    "UpdateCandidate",
    "build_bank_candidates_router",
    "build_engagement_bank_router",
    "build_meeting_bank_router",
    "build_question_bank_tree",
    "recompile_meeting_bank",
]
