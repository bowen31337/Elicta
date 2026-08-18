"""Context-completeness scoring for a single engagement.

Scores the six context fields this package owns end to end: the three
`EngagementCreateRequest` captures at creation (`client_organisation`,
`sector`, `commercial_context` — always populated, since that request
requires them) plus the three `EngagementUpdateRequest` fills in later
(`purpose`, `scope_boundary`, `target_requirements_template` — each `None`
until a PATCH supplies it). The score is the fraction of those six fields
that are populated, so a freshly created engagement with no PATCH yet scores
0.5 rather than 0 or 1.
"""

from app.modules.engagement.api.schemas import EngagementRecord

CONTEXT_FIELDS = (
    "client_organisation",
    "sector",
    "commercial_context",
    "purpose",
    "scope_boundary",
    "target_requirements_template",
)


def compute_context_completeness_score(engagement: EngagementRecord) -> float:
    filled = sum(1 for field in CONTEXT_FIELDS if getattr(engagement, field))
    return filled / len(CONTEXT_FIELDS)
