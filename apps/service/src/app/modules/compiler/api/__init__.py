"""Compiler API package: the per-meeting recompiled question bank (PRD FR-4.8).

Exposes no mounted router -- `build_meeting_bank_router` needs
`get_base_candidates` and `get_inherited_open_questions` injected first, and
`build_bank_candidates_router` needs `delete_candidate` injected first -- so
this package is consumed directly by whoever wires the app factory.
`GET /api/meetings/{meeting_id}/bank` always returns 200: a meeting with no
compiled candidates and no inherited open questions simply gets back an
empty `candidates` list rather than a 404, since a per-meeting bank has no
"not found" state the way a single persisted row does. `DELETE
/api/bank/candidates/{id}` returns 204, or 404 if `delete_candidate` raises
`CandidateNotFoundError`.
"""

from __future__ import annotations

from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.models import BankCandidate, MeetingQuestionBank
from app.modules.compiler.api.recompile import (
    INHERITED_TEMPLATE_SECTION,
    InheritedOpenQuestion,
    recompile_meeting_bank,
)
from app.modules.compiler.api.router import (
    DeleteCandidate,
    GetBaseCandidates,
    GetInheritedOpenQuestions,
    build_bank_candidates_router,
    build_meeting_bank_router,
)

__all__ = [
    "INHERITED_TEMPLATE_SECTION",
    "BankCandidate",
    "CandidateNotFoundError",
    "DeleteCandidate",
    "GetBaseCandidates",
    "GetInheritedOpenQuestions",
    "InheritedOpenQuestion",
    "MeetingQuestionBank",
    "build_bank_candidates_router",
    "build_meeting_bank_router",
    "recompile_meeting_bank",
]
