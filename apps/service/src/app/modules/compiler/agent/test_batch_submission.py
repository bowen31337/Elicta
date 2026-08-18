"""Tests for submitting the offline BMAD Analyst pass to the Batch API (architecture §14.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.compiler.agent.batch_submission import submit_bmad_analyst_batch
from app.modules.compiler.agent.models import (
    AnalystContextPack,
    BmadAnalystBatchSubmissionStatus,
    ContextPackDocument,
    EngagementBmadAnalystBatchSubmission,
)
from app.modules.engagement.documents.models import DocumentStatus

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_context_pack() -> AnalystContextPack:
    return AnalystContextPack(
        engagement_id="engagement-1",
        sector="technology",
        project_type="greenfield",
        documents=[
            ContextPackDocument(
                document_id="doc-1",
                status=DocumentStatus.GROUND_TRUTH,
                text="The client wants a new billing system.",
            )
        ],
    )


def make_submit(job_id: str | None = None, *, fail: bool = False):
    async def submit(engagement_id: str, context_pack: AnalystContextPack) -> str:
        if fail:
            raise RuntimeError("batch API rejected the workload")
        return job_id or "batch-job-1"

    return submit


def test_a_successful_submission_persists_exactly_one_batch_job_id():
    saved: list[EngagementBmadAnalystBatchSubmission] = []

    async def save(record: EngagementBmadAnalystBatchSubmission) -> None:
        saved.append(record)

    result = asyncio.run(
        submit_bmad_analyst_batch(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_submit("batch-job-1"),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystBatchSubmissionStatus.SUBMITTED
    assert result.engagement_id == "engagement-1"
    assert result.engine == "analyst-a"
    assert result.batch_job_id == "batch-job-1"
    assert isinstance(result.batch_job_id, str)
    assert saved == [result]


def test_a_failed_submission_persists_a_failed_record_with_no_batch_job_id():
    saved: list[EngagementBmadAnalystBatchSubmission] = []

    async def save(record: EngagementBmadAnalystBatchSubmission) -> None:
        saved.append(record)

    result = asyncio.run(
        submit_bmad_analyst_batch(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_submit(fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystBatchSubmissionStatus.FAILED
    assert result.engagement_id == "engagement-1"
    assert result.engine == "analyst-a"
    assert result.batch_job_id is None
    assert result.error == "batch API rejected the workload"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    result = asyncio.run(
        submit_bmad_analyst_batch(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_submit("batch-job-1"),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.completed_at >= result.requested_at
