"""Computes an engagement's context-completeness indicator (PRD FR-3.14).

An operator walking into a session needs to know up front what quality of
support to expect: a context pack with a defined purpose, a scoped
boundary, grounded documents, profiled attendees, and captured reference
claims supports confident answers, while a sparse one means the operator
should expect more gaps and verify more live. `compute_context_completeness`
is a pure function over a `ContextPackSignals` snapshot — the caller (out of
this feature's footprint) is responsible for gathering that snapshot from
the engagement's actual purpose/scope fields (`api/schemas.py`), documents
(`documents/models.py`), attendees (`meetings/models.py`), and reference
claims (`state/models.py`), since none of those stores live in this module.
The indicator is derived fresh from current state rather than persisted, so
it can never go stale relative to the context pack it describes.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CompletenessLevel(str, Enum):
    """How much of the context pack is filled in, coarsest signal first (PRD FR-3.14)."""

    MINIMAL = "minimal"
    PARTIAL = "partial"
    SUBSTANTIAL = "substantial"
    COMPLETE = "complete"


class ContextPackSignals(BaseModel):
    """Presence/absence of each context-pack element the indicator scores (PRD FR-3.14).

    Each field is a plain boolean rather than a count or the underlying
    object, since completeness only cares whether an element exists at all,
    not how many: one ground-truth document and ten both count as the
    element being present.
    """

    engagement_id: str = Field(min_length=1)
    has_purpose: bool
    has_scope_boundary: bool
    has_target_requirements_template: bool
    has_ground_truth_document: bool
    has_structured_attendee: bool
    has_reference_claim: bool


class ContextCompleteness(BaseModel):
    """The computed indicator for one engagement (PRD FR-3.14).

    `missing_elements` names the absent signals so the UI can tell the
    operator *what* quality of support to expect, not just a bare level --
    e.g. surfacing "no scope boundary set" rather than only "partial".
    """

    engagement_id: str = Field(min_length=1)
    level: CompletenessLevel
    present_count: int
    total_count: int
    missing_elements: list[str]


# Ordered so `missing_elements` lists the more structurally significant gaps
# (purpose, scope, requirements template) ahead of supplementary ones
# (documents, attendees, claims), regardless of dict insertion order.
_SIGNAL_LABELS: dict[str, str] = {
    "has_purpose": "purpose",
    "has_scope_boundary": "scope_boundary",
    "has_target_requirements_template": "target_requirements_template",
    "has_ground_truth_document": "ground_truth_document",
    "has_structured_attendee": "structured_attendee",
    "has_reference_claim": "reference_claim",
}


def compute_context_completeness(signals: ContextPackSignals) -> ContextCompleteness:
    """Scores a context-pack snapshot into a `CompletenessLevel` (PRD FR-3.14).

    The six tracked signals are weighted equally: none of them alone
    determines support quality, but each one present raises confidence and
    each one absent is a concrete gap the operator may hit. Level bands split
    the possible 0-6 present count into quarters (minimal: 0-1, partial: 2-3,
    substantial: 4-5, complete: 6) so the indicator moves in visible steps as
    the context pack fills in, rather than jumping straight from "nothing" to
    "everything".
    """

    present = {name: getattr(signals, name) for name in _SIGNAL_LABELS}
    present_count = sum(present.values())
    total_count = len(_SIGNAL_LABELS)
    missing_elements = [label for name, label in _SIGNAL_LABELS.items() if not present[name]]

    if present_count <= 1:
        level = CompletenessLevel.MINIMAL
    elif present_count <= 3:
        level = CompletenessLevel.PARTIAL
    elif present_count <= 5:
        level = CompletenessLevel.SUBSTANTIAL
    else:
        level = CompletenessLevel.COMPLETE

    return ContextCompleteness(
        engagement_id=signals.engagement_id,
        level=level,
        present_count=present_count,
        total_count=total_count,
        missing_elements=missing_elements,
    )
