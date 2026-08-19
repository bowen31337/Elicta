"""The context compiler chain (architecture §3.10), assembled end to end.

§3.10: "Document ingestion and chunking, entity and claim extraction, then
the BMAD Analyst pass that emits the candidate bank. Runs when an engagement
is created and re-runs per meeting (FR-4.8) weighted toward the inherited
open-questions list."

Ingestion and chunking already happen at upload (`index_document`, FR-3.3).
This module drives what follows: extraction, claim structuring, and the
analyst pass that emits the bank. Every one of those stages existed with no
caller.

The analyst pass is submitted as a **batch** and collected separately rather
than awaited inline. That is not an optimisation — §3.10 describes this as
"batch, offline, minutes not seconds", so a submit/collect split is the shape
the work actually has, and holding a request open for it would be wrong.

Filesystem access is scoped per engagement before any document is read
(§3.11): an agent that can read arbitrary paths on a service tier holding
several clients' requirements data is the incident that section warns about.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.agent_permissions import FilesystemOperation
from app.modules.compiler.agent.batch_collection import collect_bmad_analyst_batch_results
from app.modules.compiler.agent.batch_submission import submit_bmad_analyst_batch
from app.modules.compiler.citations.extraction import run_document_extraction_pass
from app.modules.compiler.citations.structuring import run_claim_structuring_pass

from .engines import (
    CompilerEngines,
    enforce_filesystem_permission,
    engagement_filesystem_scope,
)

_COMPLETE = "complete"


def _completed(record: Any) -> bool:
    return getattr(getattr(record, "status", None), "value", None) == _COMPLETE


@dataclass(frozen=True)
class CompilerSinks:
    """Where each compile stage's durable record goes."""

    save_extraction: Callable[[Any], Awaitable[None]]
    save_structuring: Callable[[Any], Awaitable[None]]
    save_batch_submission: Callable[[Any], Awaitable[None]]
    save_analyst_pass: Callable[[Any], Awaitable[None]]


@dataclass
class CompileRun:
    """What the compile actually did, stage by stage."""

    engagement_id: str
    extraction: Any = None
    structuring: Any = None
    submission: Any = None
    analyst_passes: list[Any] = field(default_factory=list)
    stages_completed: list[str] = field(default_factory=list)
    stopped_at: str | None = None

    @property
    def batch_job_id(self) -> str | None:
        return getattr(self.submission, "batch_job_id", None)

    @property
    def complete(self) -> bool:
        return self.stopped_at is None


async def submit_engagement_compile(
    engagement_id: str,
    *,
    documents: list[Any],
    context_pack: Any,
    engines: CompilerEngines,
    sinks: CompilerSinks,
) -> CompileRun:
    """Run §3.10 up to and including batch submission.

    Returns as soon as the analyst batch is submitted; the results are
    collected later by `collect_engagement_compile`, since the pass runs in
    minutes rather than seconds.
    """

    run = CompileRun(engagement_id=engagement_id)
    scope = engagement_filesystem_scope(engagement_id)

    # §3.11: every document this engagement's agent reads is checked against
    # its own scope before the model ever sees it.
    for document in documents:
        enforce_filesystem_permission(
            scope,
            FilesystemOperation.READ,
            f"engagements/{engagement_id}/documents/{document.document_id}",
        )

    run.extraction = await run_document_extraction_pass(
        engagement_id, documents, engines.extract, sinks.save_extraction
    )
    if not _completed(run.extraction) or run.extraction.claims is None:
        run.stopped_at = "extraction"
        return run
    run.stages_completed.append("extraction")

    run.structuring = await run_claim_structuring_pass(
        engagement_id, run.extraction.claims, engines.structure, sinks.save_structuring
    )
    if not _completed(run.structuring):
        run.stopped_at = "structuring"
        return run
    run.stages_completed.append("structuring")

    run.submission = await submit_bmad_analyst_batch(
        engagement_id,
        context_pack,
        engines.name,
        engines.submit_batch,
        sinks.save_batch_submission,
    )
    if not _completed(run.submission) or run.submission.batch_job_id is None:
        run.stopped_at = "batch-submission"
        return run
    run.stages_completed.append("batch-submission")

    return run


async def collect_engagement_compile(
    run: CompileRun,
    *,
    engines: CompilerEngines,
    sinks: CompilerSinks,
) -> CompileRun:
    """Collect a submitted analyst batch and persist the emitted bank.

    Writing the bank is the one filesystem write §3.11 allows these agents,
    so the scope is checked here too rather than trusted.
    """

    if run.batch_job_id is None:
        run.stopped_at = run.stopped_at or "batch-submission"
        return run

    enforce_filesystem_permission(
        engagement_filesystem_scope(run.engagement_id),
        FilesystemOperation.WRITE,
        f"engagements/{run.engagement_id}/bank/candidates.json",
    )

    run.analyst_passes = await collect_bmad_analyst_batch_results(
        run.batch_job_id, engines.name, engines.fetch_batch, sinks.save_analyst_pass
    )
    if not run.analyst_passes or not all(_completed(p) for p in run.analyst_passes):
        run.stopped_at = "batch-collection"
        return run

    run.stages_completed.append("batch-collection")
    return run
