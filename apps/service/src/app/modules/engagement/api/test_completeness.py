from app.modules.engagement.api.completeness import compute_context_completeness_score
from app.modules.engagement.api.schemas import EngagementRecord


def test_score_is_half_with_only_creation_fields_populated():
    engagement = EngagementRecord(
        client_organisation="Acme Corp",
        sector="Manufacturing",
        commercial_context="Multi-year cost reduction programme",
    )

    assert compute_context_completeness_score(engagement) == 0.5


def test_score_is_one_when_every_field_is_populated():
    engagement = EngagementRecord(
        client_organisation="Acme Corp",
        sector="Manufacturing",
        commercial_context="Multi-year cost reduction programme",
        purpose="Reduce manufacturing cost base",
        scope_boundary="Excludes logistics and warehousing",
        target_requirements_template="MoSCoW",
    )

    assert compute_context_completeness_score(engagement) == 1.0


def test_score_reflects_partial_updates():
    engagement = EngagementRecord(
        client_organisation="Acme Corp",
        sector="Manufacturing",
        commercial_context="Multi-year cost reduction programme",
        purpose="Reduce manufacturing cost base",
    )

    assert compute_context_completeness_score(engagement) == 4 / 6
