"""Falls back to a generic, sector- and project-type-keyed elicitation bank (PRD FR-3.13).

An engagement with no reference documents has nothing for the compiler's
candidate pipeline (`compiler/bank`, out of this feature's footprint) to
compile a bank from, but a session still needs questions to open with.
`select_fallback_bank` is the entry point: given whether the engagement has
any reference documents -- a signal the caller assembles from
`documents/models.py`, since no document store lives in this module, the
same seam `ContextPackSignals` uses in `context_completeness.py` -- it
returns a `GenericElicitationBank` only when there are none to compile from,
so a caller never has to special-case "no documents" itself.

`build_generic_elicitation_bank` looks the bank up by `(sector,
project_type)`, degrading gracefully rather than failing on an unrecognised
value: sector-specific questions are included whenever the sector is
recognised, project-type-specific questions whenever the project type is
recognised, and a sector- and project-type-agnostic baseline set is always
included, so an engagement in an unrecognised sector or project type still
gets a usable bank rather than an empty one. Lookups are case-insensitive
and ignore surrounding whitespace, since `sector` (`EngagementCreateRequest`,
`api/schemas.py`) and `project_type` are free-text fields a caller might
submit in any casing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

SECTOR_TEMPLATE_SECTION = "generic-bank-sector"
PROJECT_TYPE_TEMPLATE_SECTION = "generic-bank-project-type"
BASELINE_TEMPLATE_SECTION = "generic-bank-baseline"

# Deliberately small, illustrative sets rather than an exhaustive taxonomy:
# each entry keys a handful of questions that are useful regardless of which
# specific engagement lands in that sector or project type. Unrecognised
# sectors/project types simply fall through to the baseline set below rather
# than raising, since this bank exists precisely for engagements the rest of
# the pipeline knows the least about.
_SECTOR_QUESTIONS: dict[str, list[str]] = {
    "healthcare": [
        "What patient data does this work touch, and what consent or de-identification rules govern it?",
        "Which clinical or regulatory bodies (e.g. HIPAA, CQC) does this work need to satisfy?",
        "Who clinically signs off on requirements before they're considered settled?",
    ],
    "financial_services": [
        "What regulatory regime applies to this work (e.g. PCI-DSS, SOX, FCA), and who owns compliance sign-off?",
        "What audit trail or reporting obligations does this system need to support?",
        "Which transactions or balances does this system need to reconcile against, and how often?",
    ],
    "retail": [
        "Which sales channels (in-store, online, marketplace) does this work need to support?",
        "How does this work need to behave during peak trading periods (e.g. seasonal sales)?",
        "What inventory or fulfilment systems does this need to stay consistent with?",
    ],
    "manufacturing": [
        "Which production lines or facilities does this work need to integrate with?",
        "What safety or quality-control standards constrain this work?",
        "How does this system need to handle planned and unplanned downtime?",
    ],
    "public_sector": [
        "Which statutory or policy obligations does this work need to satisfy?",
        "What accessibility standards (e.g. WCAG) must this work meet?",
        "Who is the accountable officer for sign-off on this work?",
    ],
    "technology": [
        "What existing platform or infrastructure does this work need to build on rather than replace?",
        "What are the expected scale and performance requirements?",
        "Which teams own the systems this work will integrate with?",
    ],
}

_PROJECT_TYPE_QUESTIONS: dict[str, list[str]] = {
    "greenfield": [
        "What does success look like for this project's first release?",
        "What existing process, if any, does this replace once live?",
    ],
    "migration": [
        "What is the cutover plan, and what happens to the legacy system afterward?",
        "What data needs to migrate, and how will its accuracy be validated after the move?",
        "Is there a rollback plan if the migration needs to be reversed?",
    ],
    "integration": [
        "Which systems are being integrated, and who owns each one?",
        "What happens when one of the integrated systems is unavailable?",
        "What is the source of truth when the integrated systems disagree?",
    ],
    "replatform": [
        "What functionality from the current platform must be preserved exactly, and what's open to change?",
        "What is driving the replatform -- cost, scale, vendor risk, or something else?",
    ],
    "compliance": [
        "What specific requirement or finding is this work responding to?",
        "What is the deadline this work is being driven by, and what happens if it's missed?",
    ],
}

_BASELINE_QUESTIONS: list[str] = [
    "Who is the ultimate decision-maker if stakeholders disagree on requirements?",
    "What is explicitly out of scope for this work?",
    "What would make this project a failure, even if every requirement is technically met?",
    "What is the timeline this work needs to land within, and what's driving it?",
]


class GenericBankCandidate(BaseModel):
    """One question in the generic fallback bank (PRD FR-3.13).

    Mirrors the small candidate shape `compiler/bank/models.py`'s
    `BankCandidate` uses (`template_section`, `phrasing`, `priority`) so a
    caller downstream can treat a generic candidate the same way it treats a
    compiled one, without this module importing that package.
    """

    id: str
    template_section: str
    phrasing: str
    priority: int = Field(ge=1)


class GenericElicitationBank(BaseModel):
    """The generic, sector- and project-type-keyed fallback bank for one engagement (PRD FR-3.13)."""

    engagement_id: str
    sector: str
    project_type: str
    candidates: list[GenericBankCandidate]
    generated_at: datetime


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def build_generic_elicitation_bank(
    engagement_id: str,
    sector: str,
    project_type: str,
    *,
    generated_at: datetime | None = None,
) -> GenericElicitationBank:
    """Builds the generic bank keyed to `sector` and `project_type` (PRD FR-3.13).

    Candidates are ordered sector block first, then project-type block, then
    the baseline -- most engagement-specific questions outrank the ones any
    engagement in any sector or project type would get -- with either keyed
    block simply omitted when its key isn't recognised, rather than
    replaced with something empty.
    """

    generated_at = generated_at or datetime.now(timezone.utc)

    blocks: list[tuple[str, list[str]]] = []
    sector_questions = _SECTOR_QUESTIONS.get(_normalize(sector))
    if sector_questions is not None:
        blocks.append((SECTOR_TEMPLATE_SECTION, sector_questions))
    project_type_questions = _PROJECT_TYPE_QUESTIONS.get(_normalize(project_type))
    if project_type_questions is not None:
        blocks.append((PROJECT_TYPE_TEMPLATE_SECTION, project_type_questions))
    blocks.append((BASELINE_TEMPLATE_SECTION, _BASELINE_QUESTIONS))

    candidates: list[GenericBankCandidate] = []
    priority = 1
    for template_section, questions in blocks:
        for local_index, phrasing in enumerate(questions):
            candidates.append(
                GenericBankCandidate(
                    id=f"{template_section}-{local_index}",
                    template_section=template_section,
                    phrasing=phrasing,
                    priority=priority,
                )
            )
            priority += 1

    return GenericElicitationBank(
        engagement_id=engagement_id,
        sector=sector,
        project_type=project_type,
        candidates=candidates,
        generated_at=generated_at,
    )


def select_fallback_bank(
    engagement_id: str,
    sector: str,
    project_type: str,
    has_reference_documents: bool,
    *,
    generated_at: datetime | None = None,
) -> GenericElicitationBank | None:
    """Returns the generic fallback bank only when the engagement has no reference documents (PRD FR-3.13).

    `has_reference_documents` is an injected signal rather than a lookup
    this module performs itself: the caller (out of this feature's
    footprint) is responsible for checking `documents/models.py` for the
    engagement, the same division of responsibility
    `compute_context_completeness` uses for its own signals. Returns `None`
    when documents exist, so a caller can compile from them instead without
    this module needing to know how that compile works.
    """

    if has_reference_documents:
        return None
    return build_generic_elicitation_bank(engagement_id, sector, project_type, generated_at=generated_at)
