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

import asyncio
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
    UpstreamFailure,
    enforce_filesystem_permission,
    engagement_filesystem_scope,
    upstream_failure_in,
)

_COMPLETE = "complete"
_SUBMITTED = "submitted"


def _completed(record: Any) -> bool:
    return getattr(getattr(record, "status", None), "value", None) == _COMPLETE


def _submitted(record: Any) -> bool:
    """Whether a batch submission got as far as a job id.

    A submission's terminal states are `SUBMITTED` and `FAILED` — there is no
    `COMPLETE`, because the pass itself finishes later and out of that record's
    view. Asking `_completed` here therefore always answered no, so every
    compile stopped at this stage and `collect_engagement_compile` had no
    reachable caller: `POST /bank/compile` returned 202 and the bank stayed
    empty for ever, with no stage reporting a failure.
    """

    return (
        getattr(getattr(record, "status", None), "value", None) == _SUBMITTED
        and getattr(record, "batch_job_id", None) is not None
    )


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
    #: Why the direct Analyst route failed, when it was tried and did. The
    #: passes carry their own records; this is the one a caller reads when the
    #: run stopped at `analyst-pass-direct`.
    direct_analyst_error: str | None = None

    @property
    def batch_job_id(self) -> str | None:
        return getattr(self.submission, "batch_job_id", None)

    @property
    def complete(self) -> bool:
        return self.stopped_at is None


#: How long a compile waits for its own batch before drafting the pass
#: directly. Minutes, because that is what §3.10 budgets and what the operator
#: is standing in front of — not the provider's twenty-four hour SLA, which is
#: a bound on the worst case rather than a promise about the usual one.
BATCH_PATIENCE_SECONDS = 180.0

#: How often the wait above asks. Cheap — a batch retrieve is one small
#: request — and short enough that a batch landing early is used promptly.
_BATCH_POLL_SECONDS = 10.0


async def submit_engagement_compile(
    engagement_id: str,
    *,
    documents: list[Any],
    context_pack: Any,
    engines: CompilerEngines,
    sinks: CompilerSinks,
    on_stage: Callable[[str], None] | None = None,
    batch_patience: float = 0.0,
) -> CompileRun:
    """Run §3.10 up to and including batch submission.

    Returns as soon as the analyst batch is submitted; the results are
    collected later by `collect_engagement_compile`, since the pass runs in
    minutes rather than seconds.

    `on_stage` is told each stage's name as that stage finishes, for whoever
    is waiting. The run records the same list, but only becomes reachable
    when this returns — so a compile in flight could say nothing at all about
    itself, and "still working" and "hung on the first call" looked identical
    for the several minutes a real one takes. Called synchronously and given
    nothing to fail on: it is a notification, not a step.
    """

    run = CompileRun(engagement_id=engagement_id)

    def completed(stage: str) -> None:
        run.stages_completed.append(stage)
        if on_stage is not None:
            on_stage(stage)
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
    completed("extraction")

    run.structuring = await run_claim_structuring_pass(
        engagement_id, run.extraction.claims, engines.structure, sinks.save_structuring
    )
    if not _completed(run.structuring):
        run.stopped_at = "structuring"
        return run
    completed("structuring")

    run.submission = await submit_bmad_analyst_batch(
        engagement_id,
        context_pack,
        engines.name,
        engines.submit_batch,
        sinks.save_batch_submission,
    )
    if not _submitted(run.submission):
        return await _analyst_without_a_batch(
            run, context_pack, engines, sinks, on_stage=on_stage
        )
    completed("batch-submission")

    # Wait for it, briefly, and draft the pass directly if it does not come.
    #
    # The Batch API has a twenty-four hour SLA and §3.10 budgets minutes, and
    # the screen this runs behind is a button somebody pressed. Those cannot
    # both be true. The one that gives is the batch: a bank drafted overnight
    # for half the price is not a saving on a screen where the operator is
    # still standing.
    #
    # Here rather than in the collector because the context pack is still in
    # scope. Collecting later would have to rebuild it, which means running
    # extraction and structuring a second time.
    #
    # The batch stays the first choice and nothing changes when it is quick.
    # Zero by default, which is this function as it has always been: submit
    # and return, leaving the batch to `collect_engagement_compile`. The wait
    # is something the application asks for — `composition` passes
    # `BATCH_PATIENCE_SECONDS` — rather than something every caller inherits.
    # A library that blocked for three minutes by default would have made
    # every test that submits a batch wait three minutes, which is exactly
    # what the first version of this did.
    if batch_patience <= 0:
        return run
    if await _batch_arrives_within(run, engines, sinks, batch_patience):
        return run
    return await _analyst_without_a_batch(
        run, context_pack, engines, sinks, on_stage=on_stage, require_refusal=False
    )



async def _batch_arrives_within(
    run: CompileRun,
    engines: CompilerEngines,
    sinks: CompilerSinks,
    patience: float,
) -> bool:
    """Poll this run's batch until it answers or the window runs out.

    Collected through `collect_engagement_compile` rather than by fetching
    here, so a batch that lands inside the window is turned into a bank by
    exactly the code that turns one landing outside it into a bank. A second
    implementation of that step is the last thing this needs.

    Answering means a bank in hand. A batch that ended and returned nothing
    usable has not answered the question that was asked of it — that is the
    case that was seen: `succeeded=1, errored=0` at the provider, a pass that
    did not meet the bank's own contract, and a compile stopped with an empty
    bank because "it ended" was being read as "it answered".

    The direct route is a different request shape against the same model, and
    has produced a full bank where a batch did not. It costs a second pass,
    which the run records as `analyst-pass-direct` so the bill is accountable.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + patience
    while True:
        run = await collect_engagement_compile(run, engines=engines, sinks=sinks)
        if run.stopped_at != "batch-collection":
            return True
        if run.analyst_passes:
            # It ended, and badly. Not an answer: the caller redrafts. The
            # passes are also what tell "ended" from "still processing" — an
            # unfinished batch collects nothing at all — so they are cleared,
            # or `_analyst_without_a_batch`'s collection would find them
            # already in hand and return the failure it was called to replace.
            run.analyst_passes = []
            return False
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        # Never past the deadline: the window is the promise being made to
        # whoever pressed the button, and a poll interval overshooting it
        # would quietly make the promise longer than it says.
        await asyncio.sleep(min(_BATCH_POLL_SECONDS, remaining))


#: The stage name a compile that bypassed the Batch API reports having run.
#: Distinct from `batch-submission` on purpose: it costs more, and a fallback
#: that leaves no trace is a bill nobody can account for.
DIRECT_ANALYST_STAGE = "analyst-pass-direct"

#: What `collect_bmad_analyst_batch_results` is handed in place of a job id
#: when there is no job. It never reaches a provider — the fetch it is passed
#: ignores it and returns results that are already in hand.
_NO_BATCH_JOB = "direct"


async def _analyst_without_a_batch(
    run: CompileRun,
    context_pack: Any,
    engines: CompilerEngines,
    sinks: CompilerSinks,
    *,
    on_stage: Callable[[str], None] | None = None,
    require_refusal: bool = True,
) -> CompileRun:
    """Run the Analyst pass directly when the batch will not do.

    A credential can be perfectly good for `/v1/messages` and carry no batch
    scope at all, and until this existed that combination meant the question
    bank could never be drafted — the compile stopped at submission and the
    screen showed an empty bank, however many times it was asked.

    Only an entitlement refusal is worth a second route. A provider that is
    unreachable or throttled will answer the direct call exactly as it answered
    the batch, so trying costs a round trip to learn what the first one said.

    The results go through the same collection the batch path uses, which is
    where the candidate-count contract and the per-engagement failure handling
    live. Bypassing that too would be a second implementation of the part most
    worth having only one of.
    """

    if engines.run_analyst is None:
        run.stopped_at = "batch-submission"
        return run

    # Two ways a batch will not do, and only one of them is a refusal. The
    # other is a batch that was accepted and has not come back inside the
    # window the operator is standing in — see `BATCH_PATIENCE_SECONDS` — and
    # there is nothing to inspect on the submission for that, because the
    # submission succeeded.
    refusal = getattr(run.submission, "error", None) or ""
    if require_refusal and upstream_failure_in(refusal) is not UpstreamFailure.NOT_ENTITLED:
        run.stopped_at = "batch-submission"
        return run

    enforce_filesystem_permission(
        engagement_filesystem_scope(run.engagement_id),
        FilesystemOperation.WRITE,
        f"engagements/{run.engagement_id}/bank/candidates.json",
    )

    async def already_in_hand(_job_id: str) -> Any:
        return await engines.run_analyst(run.engagement_id, context_pack)

    # The collection wraps each *result*, not the fetch that produces them, so
    # a provider refusing this call would otherwise travel straight out of the
    # compile — the batch path never sees that because its fetch happens in a
    # later visit, behind its own handler.
    try:
        run.analyst_passes = await collect_bmad_analyst_batch_results(
            _NO_BATCH_JOB, engines.name, already_in_hand, sinks.save_analyst_pass
        )
    except Exception as exc:  # noqa: BLE001 — recorded as this stage's failure
        run.direct_analyst_error = str(exc)
        run.stopped_at = DIRECT_ANALYST_STAGE
        return run

    if not run.analyst_passes or not all(_completed(p) for p in run.analyst_passes):
        # Named for the stage that actually failed. Reporting it as
        # `batch-submission` — which the first version did — made a fallback
        # that ran and failed indistinguishable from one that never ran, and
        # threw away the message saying why. Against a real credential that
        # looked exactly like the fallback not being wired at all.
        run.direct_analyst_error = next(
            (
                getattr(record, "error", None)
                for record in run.analyst_passes or []
                if not _completed(record)
            ),
            None,
        )
        run.stopped_at = DIRECT_ANALYST_STAGE
        return run

    run.stopped_at = None
    run.stages_completed.append(DIRECT_ANALYST_STAGE)
    if on_stage is not None:
        on_stage(DIRECT_ANALYST_STAGE)
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

    if run.analyst_passes:
        # Already in hand: this run went the direct route because its batch was
        # refused, and there is nothing to collect. Falling through would reset
        # a finished run to "stopped at batch-submission" — undoing, on the way
        # past, the work that just succeeded.
        return run

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

    # A collection only ever succeeds on a retry — the first attempt runs
    # microseconds after submission, when no batch has finished. Leaving the
    # earlier stop in place would have the run report itself stopped at the
    # stage it just completed.
    run.stopped_at = None
    run.stages_completed.append("batch-collection")
    return run
