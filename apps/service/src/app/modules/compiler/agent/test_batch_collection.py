"""Tests for collecting a completed Analyst pass batch job's results by `custom_id` (architecture §14.4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.modules.compiler.agent.batch_collection import (
    collect_bmad_analyst_batch_results,
)
from app.modules.compiler.agent.bmad_analyst import MAX_CANDIDATES, MIN_CANDIDATES
from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
    BmadAnalystPassStatus,
    BmadCandidateDraft,
    EngagementBmadAnalystPass,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_draft(index: int, **overrides) -> BmadCandidateDraft:
    defaults = {
        "template_section": "scope",
        "trigger_types": ["unquantified_adjective"],
        "phrasing": f"What does 'fast' mean for capability {index}?",
        "stub": f"clarify capability {index}",
        "lang": "en",
        "priority": index + 1,
    }
    defaults.update(overrides)
    return BmadCandidateDraft(**defaults)


def make_output(count: int) -> BmadAnalystPassOutput:
    return BmadAnalystPassOutput(candidates=[make_draft(i) for i in range(count)])


def make_fetch(raw_results: list[AnalystBatchResult]):
    async def fetch(batch_job_id: str) -> list[AnalystBatchResult]:
        return raw_results

    return fetch


def test_results_are_attributed_by_custom_id_even_when_returned_out_of_submission_order():
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    raw_results = [
        AnalystBatchResult(custom_id="engagement-2", output=make_output(MIN_CANDIDATES)),
        AnalystBatchResult(custom_id="engagement-1", output=make_output(MAX_CANDIDATES)),
    ]

    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch(raw_results),
            save,
            requested_at=FIXED,
        )
    )

    by_engagement = {record.engagement_id: record for record in results}
    assert by_engagement["engagement-2"].status == BmadAnalystPassStatus.COMPLETE
    assert len(by_engagement["engagement-2"].candidates) == MIN_CANDIDATES
    assert by_engagement["engagement-2"].candidates[0].id == "engagement-2-candidate-0"
    assert by_engagement["engagement-1"].status == BmadAnalystPassStatus.COMPLETE
    assert len(by_engagement["engagement-1"].candidates) == MAX_CANDIDATES
    assert by_engagement["engagement-1"].candidates[0].id == "engagement-1-candidate-0"
    assert saved == results


def test_a_vendor_reported_error_persists_a_failed_record_for_only_that_engagement():
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    raw_results = [
        AnalystBatchResult(custom_id="engagement-1", error="request expired before the batch completed"),
        AnalystBatchResult(custom_id="engagement-2", output=make_output(MIN_CANDIDATES)),
    ]

    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch(raw_results),
            save,
            requested_at=FIXED,
        )
    )

    by_engagement = {record.engagement_id: record for record in results}
    assert by_engagement["engagement-1"].status == BmadAnalystPassStatus.FAILED
    assert by_engagement["engagement-1"].candidates is None
    assert by_engagement["engagement-1"].error == "request expired before the batch completed"
    assert by_engagement["engagement-2"].status == BmadAnalystPassStatus.COMPLETE
    assert saved == results


@pytest.mark.parametrize(
    "count",
    [0, 1, MIN_CANDIDATES - 1, MAX_CANDIDATES + 1, MAX_CANDIDATES * 2],
    ids=["none", "one", "just-under", "just-over", "far-over"],
)
def test_a_candidate_count_outside_the_accepted_band_fails_only_that_engagement(count: int):
    raw_results = [
        AnalystBatchResult(custom_id="engagement-1", output=make_output(count)),
        AnalystBatchResult(custom_id="engagement-2", output=make_output(MIN_CANDIDATES)),
    ]

    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch(raw_results),
            lambda record: asyncio.sleep(0),
        )
    )

    by_engagement = {record.engagement_id: record for record in results}
    assert by_engagement["engagement-1"].status == BmadAnalystPassStatus.FAILED
    assert str(count) in by_engagement["engagement-1"].error
    assert str(MIN_CANDIDATES) in by_engagement["engagement-1"].error
    assert by_engagement["engagement-2"].status == BmadAnalystPassStatus.COMPLETE


def test_a_result_with_neither_output_nor_error_fails_that_engagement():
    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch([AnalystBatchResult(custom_id="engagement-1")]),
            lambda record: asyncio.sleep(0),
        )
    )

    assert results[0].status == BmadAnalystPassStatus.FAILED
    assert results[0].engagement_id == "engagement-1"
    assert results[0].candidates is None


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch([AnalystBatchResult(custom_id="engagement-1", output=make_output(MIN_CANDIDATES))]),
            lambda record: asyncio.sleep(0),
        )
    )

    assert results[0].completed_at >= results[0].requested_at


def test_no_results_persists_nothing():
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    results = asyncio.run(
        collect_bmad_analyst_batch_results(
            "batch-job-1",
            "analyst-a",
            make_fetch([]),
            save,
        )
    )

    assert results == []
    assert saved == []
