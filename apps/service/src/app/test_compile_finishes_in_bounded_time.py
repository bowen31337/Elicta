"""A compile an operator is waiting on finishes in bounded time.

Reported twice as "compiling takes for ever". The first report was a batch
that had errored and was being described as still on its way; that is fixed.
The second is this: with a working credential the batch is accepted and the
compile is correct in every respect, and the operator waits.

Anthropic's Batch API has a twenty-four hour SLA. Architecture section 3.10
budgets *minutes* for this work, and the screen is a button somebody pressed.
Those cannot both be true, and the one that gives is the batch: a bank drafted
overnight for half the price is not a saving on a screen where the operator is
still standing.

So the compile waits a bounded time for the batch it submitted, and drafts the
pass directly when that runs out. The context pack is still in scope there,
which is why this belongs in the compile rather than in the collector — the
collector would have to rebuild it, which means running extraction and
structuring again.

The batch stays the first choice. It is cheaper, it usually lands well inside
the window, and nothing here changes what happens when it does.
"""

from __future__ import annotations

import asyncio

import pytest

from app.orchestration.compiler import (
    DIRECT_ANALYST_STAGE,
    CompilerSinks,
    submit_engagement_compile,
)
from app.orchestration.engines import CompilerEngines


def _pack() -> object:
    """The context the analyst pass is drafted from.

    Opaque on purpose: `submit_engagement_compile` only ever hands it to the
    engines, and the engines here are stubs. What is under test is which route
    the compile takes, not what it sends.
    """

    return object()


def _sinks() -> CompilerSinks:
    async def keep(_record):
        return None

    return CompilerSinks(
        save_extraction=keep,
        save_structuring=keep,
        save_batch_submission=keep,
        save_analyst_pass=keep,
    )


def _engines(*, batch_ready: bool, direct: list | None = None) -> CompilerEngines:
    from app.modules.compiler.agent.models import (
        AnalystBatchResult,
        BmadAnalystPassOutput,
        BmadCandidateDraft,
    )

    # Ten, because the bank has a floor and a pass that misses it is refused —
    # which is a different failure from the one under test and would mask it.
    drafted = BmadAnalystPassOutput(
        candidates=[
            BmadCandidateDraft(
                template_section="Volumes",
                trigger_types=["unquantified_amount"],
                phrasing=f"How many joiners are in intake {n}?",
                stub=f"how many in intake {n}?",
                lang="en",
                priority=n,
            )
            for n in range(1, 11)
        ]
    )

    async def extract(*_a, **_k):
        from app.modules.compiler.citations.models import DocumentExtractionOutput

        return DocumentExtractionOutput(claims=[])

    async def structure(*_a, **_k):
        from app.modules.compiler.citations.models import ClaimStructuringOutput

        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(*_a, **_k):
        return "batch-1"

    async def fetch_batch(_job):
        # Empty is what a batch still with the provider returns.
        return [AnalystBatchResult(custom_id="eng-1", output=drafted, error=None)] if batch_ready else []

    async def run_analyst(*_a, **_k):
        (direct if direct is not None else []).append("called")
        return [AnalystBatchResult(custom_id="eng-1", output=drafted, error=None)]

    return CompilerEngines(
        name="stub",
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
        run_analyst=run_analyst,
    )


@pytest.mark.asyncio
async def test_a_batch_that_lands_inside_the_window_is_used_as_it_is():
    """The cheap path, unchanged, whenever the provider is quick."""

    called: list[str] = []
    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=_pack(),
        engines=_engines(batch_ready=True, direct=called),
        sinks=_sinks(),
        batch_patience=0.2,
    )

    assert called == [], "the batch answered; nothing should have been redrafted"
    assert DIRECT_ANALYST_STAGE not in run.stages_completed


@pytest.mark.asyncio
async def test_a_batch_that_does_not_land_is_drafted_directly_instead():
    """The whole point: an operator gets a bank rather than a wait."""

    called: list[str] = []
    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=_pack(),
        engines=_engines(batch_ready=False, direct=called),
        sinks=_sinks(),
        batch_patience=0.2,
    )

    assert called == ["called"], "the window ran out and nothing drafted the pass"
    assert DIRECT_ANALYST_STAGE in run.stages_completed, (
        "and it has to say so: the direct route costs more, and a fallback "
        "that leaves no trace is a bill nobody can account for"
    )
    assert run.stopped_at is None, run.stopped_at


@pytest.mark.asyncio
async def test_waiting_is_bounded_even_when_the_provider_never_answers():
    """A compile that cannot be waited out is the failure being fixed."""

    called: list[str] = []
    began = asyncio.get_running_loop().time()
    await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=_pack(),
        engines=_engines(batch_ready=False, direct=called),
        sinks=_sinks(),
        batch_patience=0.2,
    )

    assert asyncio.get_running_loop().time() - began < 5, "the wait was not bounded"


def _engines_answering_uselessly(direct: list) -> CompilerEngines:
    """A batch that succeeds at the provider and returns nothing usable.

    Which is what happened: `succeeded=1, errored=0` at Anthropic, and a
    compile stopped at `batch-collection` with an empty bank. A batch is only
    an answer if it answers.
    """

    from app.modules.compiler.agent.models import AnalystBatchResult

    good = _engines(batch_ready=False, direct=direct)

    async def fetch_batch(_job):
        return [
            AnalystBatchResult(
                custom_id="eng-1",
                output=None,
                error="analyst pass produced 1 candidates, outside the accepted 10-300 range",
            )
        ]

    return CompilerEngines(
        name="stub",
        extract=good.extract,
        structure=good.structure,
        submit_batch=good.submit_batch,
        fetch_batch=fetch_batch,
        run_analyst=good.run_analyst,
    )


@pytest.mark.asyncio
async def test_a_batch_that_answers_uselessly_is_still_redrafted_directly():
    """A batch is only an answer if it answers.

    Treating "ended badly" as an answer left the operator with no bank and a
    compile that had stopped: the batch succeeded at the provider, returned a
    pass that did not meet the bank's own contract, and nothing tried the
    other route. The direct route is a different request shape against the
    same model, and it has produced a full bank where a batch did not.
    """

    called: list[str] = []
    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=_pack(),
        engines=_engines_answering_uselessly(called),
        sinks=_sinks(),
        batch_patience=0.2,
    )

    assert called == ["called"], "the batch produced no bank and nothing else was tried"
    assert DIRECT_ANALYST_STAGE in run.stages_completed
    assert run.stopped_at is None
