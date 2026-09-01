"""What a compile did outlives the process that did it.

`compile_runs` and `bank_compiles` were plain dicts and lists, so a restart
erased both: the endpoint answered "no bank compile has run for this
engagement" about an engagement that had been compiled minutes earlier, and
the Preparation screen showed no meter, no stage, and no reason. Every failure
this session's compile work made visible went invisible again at the next
launch — which, given how often the app is rebuilt, is most of the time.

The third case is the one worth naming. A compile that was *running* when the
process died is neither finished nor in flight: the task is gone and nothing
will ever finish it. Reported as running it is a spinner nobody can stop;
reported as never-run it is a lie about work that was done and billed. It
says what happened.
"""

from __future__ import annotations

import contextlib
import time

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import CompilerEngines


@contextlib.contextmanager
def _client(url: str, engines: CompilerEngines | None = None):
    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    kwargs = {"compiler_engines": engines} if engines is not None else {}
    with TestClient(build_app(backend, **kwargs)) as client:
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


def _engines(*, stop_at: str | None = None) -> CompilerEngines:
    from app.modules.compiler.agent.models import AnalystBatchResult
    from app.modules.compiler.citations.models import (
        ClaimStructuringOutput,
        DocumentExtractionOutput,
    )
    from app.orchestration.engines import (
        STAGE_STRUCTURE,
        UpstreamFailure,
        UpstreamUnavailableError,
    )

    async def extract(*_a, **_k):
        return DocumentExtractionOutput(claims=[])

    async def structure(*_a, **_k):
        if stop_at == 'structuring':
            raise UpstreamUnavailableError(
                STAGE_STRUCTURE, UpstreamFailure.UNAVAILABLE, "the provider refused."
            )
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(*_a, **_k):
        return "batch-1"

    async def fetch_batch(_job):
        return []

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


def _engagement(client: TestClient) -> str:
    made = client.post(
        "/api/engagements",
        json={"client_organisation": "Durable", "sector": "s", "commercial_context": "c"},
    )
    engagement_id = made.json()["engagement_id"]
    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("brief.txt", b"We onboard a lot of joiners.", "text/plain")},
        data={"name": "brief.txt", "status": "ground truth"},
    )
    return engagement_id


def _settle(client: TestClient, engagement_id: str) -> dict:
    deadline = time.time() + 20
    while time.time() < deadline:
        response = client.get(f"/api/engagements/{engagement_id}/bank/compile")
        if response.status_code == 200 and response.json().get("state") not in {
            "running",
            "awaiting",
        }:
            return response.json()
        time.sleep(0.1)
    raise AssertionError("the compile never settled")


def test_a_finished_compile_is_still_there_after_a_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, _backend):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")
        before = _settle(client, engagement_id)
        assert before["complete"] is True, before

    with _client(url) as (client, _backend):
        after = client.get(f"/api/engagements/{engagement_id}/bank/compile")

    assert after.status_code == 200, (
        "the screen went back to 'no bank compile has run' about an engagement "
        "that had just been compiled"
    )
    assert after.json()["complete"] is True
    assert after.json()["stages_completed"] == before["stages_completed"]


def test_why_a_compile_stopped_is_still_there_after_a_restart(tmp_path):
    """The reason is the part that had nowhere else to live."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(stop_at='structuring')) as (client, _backend):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")
        before = _settle(client, engagement_id)
        assert before["stopped_at"] == "structuring", before

    with _client(url) as (client, _backend):
        after = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert after["stopped_at"] == "structuring"
    assert after["cause"] == before["cause"]


def test_a_compile_the_process_died_during_says_so(tmp_path):
    """Neither finished nor in flight, and it must not claim to be either.

    Reported as running it is a spinner nobody can stop; reported as never-run
    it is a lie about work that was done and billed.
    """

    import asyncio

    async def never_answers(*_a, **_k):
        # A stage that does not come back, so the row stays open and the
        # process ends holding it. That is what a rebuild in the middle of a
        # compile looks like, and nothing shorter reproduces it: a stub that
        # returns closes the row on its way out.
        await asyncio.sleep(3600)

    hanging = _engines()
    hanging = type(hanging)(
        name=hanging.name,
        extract=never_answers,
        structure=hanging.structure,
        submit_batch=hanging.submit_batch,
        fetch_batch=hanging.fetch_batch,
        run_analyst=hanging.run_analyst,
    )

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, hanging) as (client, _backend):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")
        time.sleep(0.2)

    with _client(url) as (client, _backend):
        after = client.get(f"/api/engagements/{engagement_id}/bank/compile")

    assert after.status_code == 200, after.text
    body = after.json()
    assert body["state"] == "stopped", body
    assert body["complete"] is False
    assert "closed" in (body["reason"] or "").lower(), body
