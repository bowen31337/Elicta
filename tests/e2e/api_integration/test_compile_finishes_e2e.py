"""Pressing Compile produces a bank, in bounded time, through the real API.

The unit tests beside this one cover which route the compile takes. This
covers the thing that was actually reported twice: an operator presses the
button and waits, and nothing ever arrives.

Driven through the production composition root — the real endpoint, the real
scheduling, the real state store — so what is asserted is the assembly that
ships. The engines are stubs, because the failure was never in the model: it
was in a batch that could not be waited out, and a stub that never answers
reproduces that exactly.
"""

from __future__ import annotations

import contextlib
import time

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import CompilerEngines


@contextlib.contextmanager
def _client(url: str, engines: CompilerEngines):
    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend, compiler_engines=engines)) as client:
        yield client, backend
    store.close()


def _drafted():
    from app.modules.compiler.agent.models import BmadAnalystPassOutput, BmadCandidateDraft

    return BmadAnalystPassOutput(
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


def _engines(*, batch_answers: bool) -> CompilerEngines:
    """A provider whose batch either lands or never does."""

    from app.modules.compiler.agent.models import AnalystBatchResult
    from app.modules.compiler.citations.models import (
        ClaimStructuringOutput,
        DocumentExtractionOutput,
    )

    async def extract(*_a, **_k):
        return DocumentExtractionOutput(claims=[])

    async def structure(*_a, **_k):
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(*_a, **_k):
        return "batch-1"

    async def fetch_batch(_job):
        if not batch_answers:
            # What a batch still with the provider returns, for ever.
            return []
        return [AnalystBatchResult(custom_id="eng-1", output=_drafted(), error=None)]

    async def run_analyst(*_a, **_k):
        return [AnalystBatchResult(custom_id="eng-1", output=_drafted(), error=None)]

    return CompilerEngines(
        name="stub",
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
        run_analyst=run_analyst,
    )


def _engagement_with_a_document(client: TestClient) -> str:
    made = client.post(
        "/api/engagements",
        json={"client_organisation": "Bounded", "sector": "s", "commercial_context": "c"},
    )
    engagement_id = made.json()["engagement_id"]
    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("brief.txt", b"We onboard a lot of joiners each intake.", "text/plain")},
        data={"name": "brief.txt", "status": "ground truth"},
    )
    return engagement_id


def _settle(client: TestClient, engagement_id: str, seconds: float = 30.0) -> dict:
    """Poll the compile until it is neither running nor waiting."""

    deadline = time.time() + seconds
    body: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/engagements/{engagement_id}/bank/compile")
        if response.status_code == 200:
            body = response.json()
            if body.get("state") not in {"running", "awaiting"}:
                return body
        time.sleep(0.2)
    raise AssertionError(f"the compile never settled: {body}")


def _shorten_the_window(monkeypatch, *, seconds: float) -> None:
    """Ask for a shorter wait than a deployment would.

    Patched on `composition`, which is where the value is read: the compile
    takes it as an argument precisely so the application decides it, and a
    library default of three minutes would make every test that submits a
    batch wait three minutes.
    """

    import app.composition as composition
    import app.orchestration.compiler as compiler

    monkeypatch.setattr(composition, "BATCH_PATIENCE_SECONDS", seconds)
    monkeypatch.setattr(compiler, "_BATCH_POLL_SECONDS", 0.1)


def _bank_size(client: TestClient, engagement_id: str) -> int:
    bank = client.get(f"/api/engagements/{engagement_id}/bank").json()
    return sum(len(section.get("candidates", [])) for section in bank.get("sections", []))


def test_pressing_compile_produces_a_bank_when_the_batch_answers(tmp_path, monkeypatch):
    """The cheap path, and the one that should stay unchanged."""

    # The window the application asks for, shortened. `composition` reads the
    # constant when it calls the compile, so patching it here is what the
    # deployment's own setting would be.
    _shorten_the_window(monkeypatch, seconds=5.0)

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(batch_answers=True)) as (client, _backend):
        engagement_id = _engagement_with_a_document(client)
        assert client.post(f"/api/engagements/{engagement_id}/bank/compile").status_code == 202

        outcome = _settle(client, engagement_id)

        assert outcome["complete"] is True, outcome
        assert _bank_size(client, engagement_id) == 10


def test_pressing_compile_still_produces_a_bank_when_the_batch_never_answers(
    tmp_path, monkeypatch
):
    """The report, twice over: "it still takes for ever".

    A batch that never comes back used to leave the compile `awaiting`
    indefinitely and the bank empty. The wait is bounded now, and what the
    operator gets at the end of it is a bank rather than a longer wait.
    """

    _shorten_the_window(monkeypatch, seconds=1.0)

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(batch_answers=False)) as (client, backend):
        engagement_id = _engagement_with_a_document(client)
        began = time.time()
        client.post(f"/api/engagements/{engagement_id}/bank/compile")

        outcome = _settle(client, engagement_id)
        took = time.time() - began

    assert outcome["complete"] is True, outcome
    assert "analyst-pass-direct" in outcome["stages_completed"], (
        "the batch never answered, so the pass has to have been drafted directly"
    )
    assert took < 25, f"the operator waited {took:.0f}s on a one-second window"
