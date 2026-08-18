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
"""

from __future__ import annotations

from app.modules.engagement.state.context_completeness import (
    CompletenessLevel,
    ContextCompleteness,
    ContextPackSignals,
    compute_context_completeness,
)
from app.modules.engagement.state.models import ReferenceClaim
from app.modules.engagement.state.reference_claims import (
    LoadReferenceClaim,
    SaveReferenceClaim,
    set_verify_with_client,
)

__all__ = [
    "CompletenessLevel",
    "ContextCompleteness",
    "ContextPackSignals",
    "LoadReferenceClaim",
    "ReferenceClaim",
    "SaveReferenceClaim",
    "compute_context_completeness",
    "set_verify_with_client",
]
