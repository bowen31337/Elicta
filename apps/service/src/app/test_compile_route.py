"""A compile somebody is waiting on does not send a batch at all.

Measured against the provider after the schema fix, every batch that
*succeeded* took longer than the window set to wait for one:

    202s   ok=1
    307s   ok=1
    501s   ok=1

The window was a hundred and eighty seconds. So it could only ever lose: the
compile waited three minutes for a batch that was never going to arrive in
three minutes, then drafted the pass directly anyway — and the batch went on
to finish and be billed. Slowest *and* dearest, which is the one combination
worth ruling out.

Dropping the batch for this route makes an operator-triggered compile both
quicker and cheaper than it is today: one pass instead of two, and none of
the dead time. The batch is still the right shape for work nobody is waiting
on, and everything that collects one is untouched — this only decides what
the button sends.
"""

from __future__ import annotations

import pytest

from app.orchestration.compiler import (
    DIRECT_ANALYST_STAGE,
    CompilerSinks,
    submit_engagement_compile,
)
from app.orchestration.engines import CompilerEngines


def _sinks() -> CompilerSinks:
    async def keep(_record):
        return None

    return CompilerSinks(
        save_extraction=keep,
        save_structuring=keep,
        save_batch_submission=keep,
        save_analyst_pass=keep,
    )


def _engines(log: list[str]) -> CompilerEngines:
    from app.modules.compiler.agent.models import (
        AnalystBatchResult,
        BmadAnalystPassOutput,
        BmadCandidateDraft,
    )
    from app.modules.compiler.citations.models import (
        ClaimStructuringOutput,
        DocumentExtractionOutput,
    )

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
        return DocumentExtractionOutput(claims=[])

    async def structure(*_a, **_k):
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(*_a, **_k):
        log.append("batch")
        return "batch-1"

    async def fetch_batch(_job):
        return []

    async def run_analyst(*_a, **_k):
        log.append("direct")
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
async def test_the_direct_route_sends_no_batch_and_drafts_at_once():
    """No dead time, and one pass rather than two."""

    log: list[str] = []
    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=object(),
        engines=_engines(log),
        sinks=_sinks(),
        route="direct",
    )

    assert log == ["direct"], f"a batch was sent on the direct route: {log}"
    assert DIRECT_ANALYST_STAGE in run.stages_completed
    assert run.stopped_at is None


@pytest.mark.asyncio
async def test_the_batch_route_is_unchanged_and_stays_the_default():
    """Work nobody is waiting on still belongs in a batch."""

    log: list[str] = []
    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=object(),
        engines=_engines(log),
        sinks=_sinks(),
    )

    assert log == ["batch"]
    assert "batch-submission" in run.stages_completed
    assert DIRECT_ANALYST_STAGE not in run.stages_completed


@pytest.mark.asyncio
async def test_the_direct_route_still_falls_back_to_a_batch_it_cannot_avoid():
    """A deployment with no direct route configured must still compile."""

    log: list[str] = []
    engines = _engines(log)
    without_direct = CompilerEngines(
        name=engines.name,
        extract=engines.extract,
        structure=engines.structure,
        submit_batch=engines.submit_batch,
        fetch_batch=engines.fetch_batch,
        run_analyst=None,
    )

    run = await submit_engagement_compile(
        "eng-1",
        documents=[],
        context_pack=object(),
        engines=without_direct,
        sinks=_sinks(),
        route="direct",
    )

    assert log == ["batch"], "with no direct route there is only the batch"
    assert "batch-submission" in run.stages_completed
