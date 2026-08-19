"""Submits the offline BMAD Analyst pass workload to the Batch API (architecture §14.4).

`submit_bmad_analyst_batch` takes the submission call itself as an injected
callable rather than importing the Claude Agent SDK directly, mirroring
`bmad_analyst.py`'s `run_bmad_analyst_pass`: this package stays decoupled
from any concrete vendor client. Whoever wires the app factory supplies the
real call -- built on the Claude Agent SDK's Batch API per architecture
§14.4 -- as `SubmitBmadAnalystBatch`.

Architecture §14.4 is explicit that running the compiler on the Batch API is
"the single largest cost reduction available in the system": it halves
inference cost on a pass that §3.10 already states has no latency
constraint. Submitting is a synchronous vendor call that returns a job id
immediately; the workload itself runs to completion later, out of this
module's view. Collecting that job's results -- keyed by `custom_id`, never
by position, per §14.4 -- and turning them into an `EngagementBmadAnalystPass`
is a separate, downstream concern this module has no reason to perform
itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .models import (
    AnalystContextPack,
    BmadAnalystBatchSubmissionStatus,
    EngagementBmadAnalystBatchSubmission,
)

SubmitBmadAnalystBatch = Callable[[str, AnalystContextPack], Awaitable[str]]
SaveEngagementBmadAnalystBatchSubmission = Callable[[EngagementBmadAnalystBatchSubmission], Awaitable[None]]


async def submit_bmad_analyst_batch(
    engagement_id: str,
    context_pack: AnalystContextPack,
    engine: str,
    submit: SubmitBmadAnalystBatch,
    save: SaveEngagementBmadAnalystBatchSubmission,
    *,
    requested_at: datetime | None = None,
) -> EngagementBmadAnalystBatchSubmission:
    """Submit `context_pack`'s Analyst pass workload to the Batch API and persist the resulting job id (architecture §14.4).

    On success, persists one `SUBMITTED` record carrying the vendor-assigned
    `batch_job_id` `submit` returned. On failure, persists a `FAILED` record
    with no job id and re-raises nothing -- same shape as
    `run_bmad_analyst_pass`'s failure handling, so an engagement that hasn't
    been submitted yet stays distinguishable from one whose submission
    attempt failed.
    """

    requested_at = requested_at or datetime.now(UTC)

    try:
        batch_job_id = await submit(engagement_id, context_pack)
    except Exception as exc:
        failed = EngagementBmadAnalystBatchSubmission(
            engagement_id=engagement_id,
            status=BmadAnalystBatchSubmissionStatus.FAILED,
            engine=engine,
            batch_job_id=None,
            requested_at=requested_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        await save(failed)
        return failed

    result = EngagementBmadAnalystBatchSubmission(
        engagement_id=engagement_id,
        status=BmadAnalystBatchSubmissionStatus.SUBMITTED,
        engine=engine,
        batch_job_id=batch_job_id,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
    await save(result)
    return result
