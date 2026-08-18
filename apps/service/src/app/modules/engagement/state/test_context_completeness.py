"""Tests for computing an engagement's context-completeness indicator (PRD FR-3.14)."""

from __future__ import annotations

from app.modules.engagement.state.context_completeness import (
    CompletenessLevel,
    ContextPackSignals,
    compute_context_completeness,
)


def make_signals(
    engagement_id: str = "engagement-1",
    has_purpose: bool = False,
    has_scope_boundary: bool = False,
    has_target_requirements_template: bool = False,
    has_ground_truth_document: bool = False,
    has_structured_attendee: bool = False,
    has_reference_claim: bool = False,
) -> ContextPackSignals:
    return ContextPackSignals(
        engagement_id=engagement_id,
        has_purpose=has_purpose,
        has_scope_boundary=has_scope_boundary,
        has_target_requirements_template=has_target_requirements_template,
        has_ground_truth_document=has_ground_truth_document,
        has_structured_attendee=has_structured_attendee,
        has_reference_claim=has_reference_claim,
    )


def test_no_signals_present_scores_minimal_with_every_element_listed_as_missing():
    result = compute_context_completeness(make_signals())

    assert result.engagement_id == "engagement-1"
    assert result.level == CompletenessLevel.MINIMAL
    assert result.present_count == 0
    assert result.total_count == 6
    assert result.missing_elements == [
        "purpose",
        "scope_boundary",
        "target_requirements_template",
        "ground_truth_document",
        "structured_attendee",
        "reference_claim",
    ]


def test_one_signal_present_still_scores_minimal():
    result = compute_context_completeness(make_signals(has_purpose=True))

    assert result.level == CompletenessLevel.MINIMAL
    assert result.present_count == 1
    assert "purpose" not in result.missing_elements


def test_two_signals_present_scores_partial():
    result = compute_context_completeness(
        make_signals(has_purpose=True, has_scope_boundary=True)
    )

    assert result.level == CompletenessLevel.PARTIAL
    assert result.present_count == 2


def test_three_signals_present_still_scores_partial():
    result = compute_context_completeness(
        make_signals(has_purpose=True, has_scope_boundary=True, has_ground_truth_document=True)
    )

    assert result.level == CompletenessLevel.PARTIAL
    assert result.present_count == 3


def test_four_signals_present_scores_substantial():
    result = compute_context_completeness(
        make_signals(
            has_purpose=True,
            has_scope_boundary=True,
            has_ground_truth_document=True,
            has_structured_attendee=True,
        )
    )

    assert result.level == CompletenessLevel.SUBSTANTIAL
    assert result.present_count == 4


def test_five_signals_present_still_scores_substantial():
    result = compute_context_completeness(
        make_signals(
            has_purpose=True,
            has_scope_boundary=True,
            has_target_requirements_template=True,
            has_ground_truth_document=True,
            has_structured_attendee=True,
        )
    )

    assert result.level == CompletenessLevel.SUBSTANTIAL
    assert result.present_count == 5
    assert result.missing_elements == ["reference_claim"]


def test_all_six_signals_present_scores_complete_with_nothing_missing():
    result = compute_context_completeness(
        make_signals(
            has_purpose=True,
            has_scope_boundary=True,
            has_target_requirements_template=True,
            has_ground_truth_document=True,
            has_structured_attendee=True,
            has_reference_claim=True,
        )
    )

    assert result.level == CompletenessLevel.COMPLETE
    assert result.present_count == 6
    assert result.total_count == 6
    assert result.missing_elements == []


def test_missing_elements_preserves_declared_order_regardless_of_which_are_absent():
    result = compute_context_completeness(
        make_signals(has_structured_attendee=True, has_scope_boundary=True)
    )

    assert result.missing_elements == [
        "purpose",
        "target_requirements_template",
        "ground_truth_document",
        "reference_claim",
    ]
