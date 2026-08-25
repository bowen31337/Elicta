"""What a compile that is still running can say about itself.

Asked of a real one: "why does compile take so long? it is just one txt
file". The screen could not answer, and neither could the API — a compile in
flight reported `stages_completed: []` for its whole life, by construction.
The pipeline records each stage as it finishes, into a `CompileRun` that only
becomes reachable once the whole chain returns.

So the one question worth asking of a long job — is it moving? — had the same
answer as a job that had hung on its first call. The length is not the
complaint; the silence is.
"""

from __future__ import annotations

import asyncio

import pytest

from app.orchestration import compiler as _compiler
from app.orchestration.compiler import (
    CompilerEngines,
    CompilerSinks,
    submit_engagement_compile,
)


@pytest.fixture(autouse=True)
def _passes(monkeypatch, request):
    """The three passes, stubbed at the seam the orchestration calls them by.

    This file is about the order the orchestration reports things in, not
    about citation grounding or batch shapes — each of which has its own
    tests, and each of which would otherwise have to be satisfied here to
    reach the line under test.
    """

    gate = getattr(request, "param", None)

    async def extraction(engagement_id, documents, run_chain, save):
        return _Record(claims=[_Record(id="c1", text="a claim")])

    async def structuring(engagement_id, claims, run_chain, save):
        if _GATE["event"] is not None:
            await _GATE["event"].wait()
        return _Record()

    async def submission(engagement_id, context_pack, name, submit, save):
        return _Record(status=_Status("submitted"), batch_job_id="job-1")

    monkeypatch.setattr(_compiler, "run_document_extraction_pass", extraction)
    monkeypatch.setattr(_compiler, "run_claim_structuring_pass", structuring)
    monkeypatch.setattr(_compiler, "submit_bmad_analyst_batch", submission)
    yield gate
    _GATE["event"] = None


#: Lets one test hold structuring open while it looks at what has been
#: reported so far.
_GATE: dict[str, asyncio.Event | None] = {"event": None}


class _Status:
    """The records carry an enum; the predicates read `.status.value`."""

    def __init__(self, value: str) -> None:
        self.value = value


class _Record:
    def __init__(self, **kw):
        self.status = _Status("complete")
        self.claims = []
        self.error = None
        for k, v in kw.items():
            setattr(self, k, v)


def _engines() -> CompilerEngines:
    async def unused(*_args, **_kw):
        raise AssertionError("the passes are stubbed; the engines are not called")

    return CompilerEngines(
        name="test",
        extract=unused,
        structure=unused,
        submit_batch=unused,
        fetch_batch=unused,
    )


def _sinks() -> CompilerSinks:
    async def save(*_args, **_kw):
        return None

    return CompilerSinks(
        save_extraction=save,
        save_structuring=save,
        save_batch_submission=save,
        save_analyst_pass=save,
    )


@pytest.mark.anyio
async def test_each_finished_stage_is_reported_as_it_finishes() -> None:
    """Not at the end. At the end there is nothing left to wonder about."""

    seen: list[str] = []
    gate = asyncio.Event()
    _GATE["event"] = gate

    task = asyncio.create_task(
        submit_engagement_compile(
            "eng-1",
            documents=[_Record(document_id="doc-1", text="hello")],
            context_pack=_Record(),
            engines=_engines(),
            sinks=_sinks(),
            on_stage=seen.append,
        )
    )
    # Extraction is done; structuring is still in the model call.
    await asyncio.sleep(0)
    for _ in range(20):
        if seen:
            break
        await asyncio.sleep(0.01)

    assert seen == ["extraction"], "a finished stage must be visible before the next ends"

    gate.set()
    await task
    assert seen == ["extraction", "structuring", "batch-submission"]


@pytest.mark.anyio
async def test_a_compile_with_no_observer_still_runs() -> None:
    """The observer is for whoever is watching, not for the work."""

    run = await submit_engagement_compile(
        "eng-1",
        documents=[_Record(document_id="doc-1", text="hello")],
        context_pack=_Record(),
        engines=_engines(),
        sinks=_sinks(),
    )

    assert run.stages_completed == ["extraction", "structuring", "batch-submission"]
