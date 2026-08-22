"""A compile that was interrupted must not read as one that never happened.

`POST /bank/compile` records the attempt and hands the work to a background
task, and the outcome route reports where that task got to. The task writes its
run whatever happens — success, or a crash it catches and records. What it does
*not* catch is cancellation, because cancellation is not an error: the process
is going away.

That leaves one window where an attempt is on record and its run is not, and
the operator has to be told something. "Not compiled yet" is the one answer
that is wrong, because they pressed the button and something did happen.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import CompilerEngines
from conftest import configured_settings_store, fake_microsoft


async def _interrupted(*_args, **_kwargs):
    """A stage that goes away with the process rather than failing.

    `CancelledError` is a `BaseException`, so it passes straight through the
    `except Exception` that turns a crash into a recorded run — which is the
    whole point: a cancelled task must not be resurrected as a failure.
    """

    raise asyncio.CancelledError()


async def _ok(*_args, **_kwargs):
    return type("Out", (), {"claims": [], "candidates": []})()


@contextlib.contextmanager
def _client():
    async def submit_batch(*_args, **_kwargs):  # pragma: no cover - never reached
        raise AssertionError("extraction was interrupted; nothing should submit")

    async def fetch_batch(*_args, **_kwargs):  # pragma: no cover - never reached
        raise AssertionError("nothing was submitted, so nothing can be fetched")

    engines = CompilerEngines(
        name="test-provider",
        extract=_interrupted,
        structure=_ok,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
    )
    backend = Backend()
    with TestClient(
        build_app(
            backend,
            compiler_engines=engines,
            settings_store=configured_settings_store(),
            document_transport=fake_microsoft,
        )
    ) as client:
        yield client, backend


def _engagement(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Logistics",
            "sector": "Freight",
            "commercial_context": "Depot scheduling rebuild",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def test_an_interrupted_compile_stops_reporting_itself_as_running() -> None:
    """Left in flight it would read as "still running" for ever.

    That is the one answer an operator cannot act on: they cannot wait it out
    and they cannot see a reason to fix.
    """

    with _client() as (client, backend):
        engagement_id = _engagement(client)
        accepted = client.post(f"/api/engagements/{engagement_id}/bank/compile")
        assert accepted.status_code == 202, accepted.text

        for _ in range(400):
            outcome = client.get(f"/api/engagements/{engagement_id}/bank/compile")
            if outcome.json().get("state") != "running":
                break
        else:  # pragma: no cover - the task always settles
            raise AssertionError("the interrupted compile never stopped running")

        assert backend.compile_tasks == {}, "the task was left in flight"
        # The attempt is on record even though its run is not.
        assert backend.bank_compiles, "the attempt was not recorded at all"
        assert backend.compile_runs == {}, "a cancelled task must not record a run"
        assert outcome.status_code == 404, outcome.text
