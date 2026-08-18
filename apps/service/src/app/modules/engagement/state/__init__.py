"""Engagement standing state: durable, engagement-scoped data outside any single session.

`ReferenceClaim` is one context-pack assertion for an engagement, carrying a
`verify_with_client` flag (PRD FR-3.12) for claims the user isn't confident
enough in to treat as settled background — something to actually confirm
with the client during this session. `set_verify_with_client` is the only
way that flag changes: it loads the claim via an injected `load`, flips the
flag, and persists the result via an injected `save`, since no durable store
exists yet in this codebase.

`compute_context_completeness` scores how filled-in an engagement's context
pack is, so the UI can show the operator what quality of support to expect
before a session starts (PRD FR-3.14).

`select_fallback_bank` falls back to a generic, sector- and
project-type-keyed elicitation bank for an engagement with no reference
documents to compile a bank from (PRD FR-3.13).

`build_engagement_state_router` exposes `GET /api/engagements/{id}/state`
(PRD FR-4.8, FR-8.9): the inherited open-questions list from an engagement's
most recent meeting plus its standing `RequirementsState`.
"""

from __future__ import annotations

from app.modules.engagement.state.context_completeness import (
    CompletenessLevel,
    ContextCompleteness,
    ContextPackSignals,
    compute_context_completeness,
)
from app.modules.engagement.state.generic_elicitation_bank import (
    BASELINE_TEMPLATE_SECTION,
    PROJECT_TYPE_TEMPLATE_SECTION,
    SECTOR_TEMPLATE_SECTION,
    GenericBankCandidate,
    GenericElicitationBank,
    build_generic_elicitation_bank,
    select_fallback_bank,
)
from app.modules.engagement.state.models import (
    EngagementStateResponse,
    InheritedOpenQuestion,
    ReferenceClaim,
)
from app.modules.engagement.state.reference_claims import (
    LoadReferenceClaim,
    SaveReferenceClaim,
    set_verify_with_client,
)
from app.modules.engagement.state.router import (
    GetInheritedOpenQuestions,
    GetRequirementsState,
    build_engagement_state_router,
)

__all__ = [
    "BASELINE_TEMPLATE_SECTION",
    "PROJECT_TYPE_TEMPLATE_SECTION",
    "SECTOR_TEMPLATE_SECTION",
    "CompletenessLevel",
    "ContextCompleteness",
    "ContextPackSignals",
    "EngagementStateResponse",
    "GenericBankCandidate",
    "GenericElicitationBank",
    "GetInheritedOpenQuestions",
    "GetRequirementsState",
    "InheritedOpenQuestion",
    "LoadReferenceClaim",
    "ReferenceClaim",
    "SaveReferenceClaim",
    "build_engagement_state_router",
    "build_generic_elicitation_bank",
    "compute_context_completeness",
    "select_fallback_bank",
    "set_verify_with_client",
]
