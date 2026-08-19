"""Collects a completed Analyst pass batch job's results, keyed by `custom_id` (architecture §14.4).

`batch_submission.py`'s docstring is explicit that collecting a batch job's
results -- "keyed by `custom_id`, never by position" -- is a separate,
downstream concern from submitting the workload. This module is that
concern. A batch job can bundle many engagements' Analyst pass requests
together, and the vendor's results endpoint returns every request's outcome
in arbitrary order: nothing about a result's position in that list says
which engagement it answers, only its `custom_id` does. Keying by index
instead would silently attribute one engagement's candidates to another the
moment results stop arriving in submission order.

`collect_bmad_analyst_batch_results` takes the results fetch itself as an
injected callable, mirroring `submit_bmad_analyst_batch` and
`run_bmad_analyst_pass`: this package stays decoupled from any concrete
vendor client. Whoever wires the app factory supplies the real fetch --
built on the Claude Agent SDK's Batch API per architecture §14.4 -- as
`FetchBmadAnalystBatchResults`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .bmad_analyst import (
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    SaveEngagementBmadAnalystPass,
    build_bank_candidates,
)
from .models import AnalystBatchResult, BmadAnalystPassStatus, EngagementBmadAnalystPass

FetchBmadAnalystBatchResults = Callable[[str], Awaitable[list[AnalystBatchResult]]]


async def collect_bmad_analyst_batch_results(
    batch_job_id: str,
    engine: str,
    fetch: FetchBmadAnalystBatchResults,
    save: SaveEngagementBmadAnalystPass,
    *,
    requested_at: datetime | None = None,
) -> list[EngagementBmadAnalystPass]:
    """Fetch `batch_job_id`'s raw results and persist one `EngagementBmadAnalystPass` per `custom_id` (architecture §14.4).

    Every result is attributed to the engagement named by its own
    `custom_id`, never by where it landed in the fetched list -- the same
    150-300 candidate-count contract and failure handling as
    `run_bmad_analyst_pass` then applies per engagement, so one engagement's
    malformed result can't fail every other engagement sharing this batch
    job.
    """

    requested_at = requested_at or datetime.now(UTC)
    results: list[EngagementBmadAnalystPass] = []

    for raw_result in await fetch(batch_job_id):
        engagement_id = raw_result.custom_id

        try:
            record = _build_pass_record(engagement_id, engine, raw_result, requested_at)
        except Exception as exc:
            record = EngagementBmadAnalystPass(
                engagement_id=engagement_id,
                status=BmadAnalystPassStatus.FAILED,
                engine=engine,
                candidates=None,
                requested_at=requested_at,
                completed_at=datetime.now(UTC),
                error=str(exc),
            )

        await save(record)
        results.append(record)

    return results


def _build_pass_record(
    engagement_id: str,
    engine: str,
    raw_result: AnalystBatchResult,
    requested_at: datetime,
) -> EngagementBmadAnalystPass:
    if raw_result.error is not None:
        raise RuntimeError(raw_result.error)

    if raw_result.output is None:
        raise ValueError(f"batch result for {engagement_id!r} carried neither an output nor an error")

    candidate_count = len(raw_result.output.candidates)
    if not (MIN_CANDIDATES <= candidate_count <= MAX_CANDIDATES):
        raise ValueError(
            f"analyst pass produced {candidate_count} candidates, outside the "
            f"required {MIN_CANDIDATES}-{MAX_CANDIDATES} range (PRD FR-4.1)"
        )

    candidates = build_bank_candidates(engagement_id, raw_result.output.candidates)
    return EngagementBmadAnalystPass(
        engagement_id=engagement_id,
        status=BmadAnalystPassStatus.COMPLETE,
        engine=engine,
        candidates=candidates,
        requested_at=requested_at,
        completed_at=datetime.now(UTC),
    )
