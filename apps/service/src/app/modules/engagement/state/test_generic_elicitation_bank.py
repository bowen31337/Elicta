"""Tests for the generic, sector- and project-type-keyed elicitation bank fallback (PRD FR-3.13)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.engagement.state.generic_elicitation_bank import (
    BASELINE_TEMPLATE_SECTION,
    PROJECT_TYPE_TEMPLATE_SECTION,
    SECTOR_TEMPLATE_SECTION,
    build_generic_elicitation_bank,
    select_fallback_bank,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_unrecognised_sector_and_project_type_still_returns_a_usable_baseline_only_bank():
    bank = build_generic_elicitation_bank("engagement-1", "space_mining", "terraforming", generated_at=FIXED)

    assert bank.engagement_id == "engagement-1"
    assert bank.sector == "space_mining"
    assert bank.project_type == "terraforming"
    assert bank.generated_at == FIXED
    assert len(bank.candidates) > 0
    assert all(c.template_section == BASELINE_TEMPLATE_SECTION for c in bank.candidates)


def test_recognised_sector_adds_sector_questions_ahead_of_the_baseline():
    bank = build_generic_elicitation_bank("engagement-1", "healthcare", "unrecognised_type", generated_at=FIXED)

    sections = [c.template_section for c in bank.candidates]
    assert SECTOR_TEMPLATE_SECTION in sections
    assert sections.index(SECTOR_TEMPLATE_SECTION) < sections.index(BASELINE_TEMPLATE_SECTION)
    assert PROJECT_TYPE_TEMPLATE_SECTION not in sections


def test_recognised_project_type_adds_project_type_questions_ahead_of_the_baseline():
    bank = build_generic_elicitation_bank("engagement-1", "unrecognised_sector", "migration", generated_at=FIXED)

    sections = [c.template_section for c in bank.candidates]
    assert PROJECT_TYPE_TEMPLATE_SECTION in sections
    assert sections.index(PROJECT_TYPE_TEMPLATE_SECTION) < sections.index(BASELINE_TEMPLATE_SECTION)
    assert SECTOR_TEMPLATE_SECTION not in sections


def test_sector_and_project_type_both_recognised_orders_sector_then_project_type_then_baseline():
    bank = build_generic_elicitation_bank("engagement-1", "retail", "integration", generated_at=FIXED)

    sections = [c.template_section for c in bank.candidates]
    assert sections.index(SECTOR_TEMPLATE_SECTION) < sections.index(PROJECT_TYPE_TEMPLATE_SECTION)
    assert sections.index(PROJECT_TYPE_TEMPLATE_SECTION) < sections.index(BASELINE_TEMPLATE_SECTION)


def test_priorities_are_sequential_starting_at_one_with_no_gaps_or_repeats():
    bank = build_generic_elicitation_bank("engagement-1", "retail", "integration", generated_at=FIXED)

    assert [c.priority for c in bank.candidates] == list(range(1, len(bank.candidates) + 1))


def test_candidate_ids_are_unique():
    bank = build_generic_elicitation_bank("engagement-1", "retail", "integration", generated_at=FIXED)

    ids = [c.id for c in bank.candidates]
    assert len(ids) == len(set(ids))


def test_sector_and_project_type_lookups_are_case_and_whitespace_insensitive():
    bank = build_generic_elicitation_bank("engagement-1", "  Healthcare ", "MIGRATION", generated_at=FIXED)

    sections = [c.template_section for c in bank.candidates]
    assert SECTOR_TEMPLATE_SECTION in sections
    assert PROJECT_TYPE_TEMPLATE_SECTION in sections


def test_build_defaults_generated_at_to_now_when_not_supplied():
    bank = build_generic_elicitation_bank("engagement-1", "retail", "migration")

    assert bank.generated_at.tzinfo is not None


def test_select_fallback_bank_returns_none_when_the_engagement_has_reference_documents():
    result = select_fallback_bank("engagement-1", "retail", "migration", True, generated_at=FIXED)

    assert result is None


def test_select_fallback_bank_builds_the_generic_bank_when_the_engagement_has_no_reference_documents():
    result = select_fallback_bank("engagement-1", "retail", "migration", False, generated_at=FIXED)

    assert result == build_generic_elicitation_bank("engagement-1", "retail", "migration", generated_at=FIXED)
