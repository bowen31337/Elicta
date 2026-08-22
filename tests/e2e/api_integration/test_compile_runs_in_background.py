"""`202 Accepted` has to mean accepted, not "hold on while I do it".

`POST /bank/compile` is documented as returning "the compile id rather than
holding open for it", and it held open for it: extraction, structuring and the
batch submission all ran inside the request. Measured against a real provider
it took **45 seconds** to answer 202 — a status whose whole meaning is that the
work is happening somewhere else.

That is not only a slow request. A client that times out at thirty seconds sees
a failure for a compile that is running perfectly well, and retries it, and now
two are running.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import CompilerEngines

from conftest import configured_settings_store, fake_microsoft


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


#: How long the slow stage takes. Long enough that a request which waits for
#: it cannot be mistaken for one that does not, short enough to run in a suite.
STAGE_SECONDS = 2.0


def _slow_engines() -> CompilerEngines:
    """Engines whose first stage takes measurably longer than a request should.

    A sleep rather than an event the test releases: `TestClient` drives the app
    in-process with no socket underneath, so an httpx deadline never fires and
    a stage that blocks for ever hangs the suite instead of failing it. Elapsed
    time is the thing actually under test here, so measuring it directly is
    both simpler and harder to fool.
    """

    async def extract(*_args, **_kwargs):
        await asyncio.sleep(STAGE_SECONDS)
        return type("Out", (), {"claims": []})()

    async def other(*_args, **_kwargs):
        return type("Out", (), {"claims": []})()

    return CompilerEngines(
        name="test-provider",
        extract=extract,
        structure=other,
        submit_batch=other,
        fetch_batch=other,
    )


@contextlib.contextmanager
def _client(engines: CompilerEngines):
    """A client whose event loop outlives a single request.

    `TestClient` starts and tears down a portal *per request* unless it is
    entered as a context manager. Work handed to `asyncio.create_task` inside a
    request therefore dies with the loop that request ran on, and the compile
    looks as though it never started — which is a property of this harness, not
    of the service, where one loop serves the whole process.
    """

    backend = Backend()
    app = build_app(
        backend,
        compiler_engines=engines,
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    with TestClient(app) as client:
        yield client, backend


def test_the_request_returns_long_before_the_compile_does() -> None:
    with _client(_slow_engines()) as (client, _):
        engagement_id = _engagement(client)

        started = time.monotonic()
        accepted = client.post(f"/api/engagements/{engagement_id}/bank/compile")
        elapsed = time.monotonic() - started

        assert accepted.status_code == 202
        assert accepted.json()["job_id"]
        assert elapsed < STAGE_SECONDS / 2, (
            f"the request took {elapsed:.2f}s while its first stage alone takes "
            f"{STAGE_SECONDS}s — it is still waiting for the chain"
        )


def test_a_compile_still_running_is_not_reported_as_finished() -> None:
    """The third state, and the one that did not exist.

    `complete` was derived from "no stage has stopped it", which is also true
    of a compile that has not got anywhere yet. Reporting that as complete
    would tell an operator their empty bank was the finished article.
    """

    with _client(_slow_engines()) as (client, _):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")

        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

        assert body["state"] == "running", body
        assert body["complete"] is False
        assert body["stopped_at"] is None
        assert body["cause"] is None


def test_the_outcome_is_readable_once_the_work_finishes() -> None:
    async def ok(*_args, **_kwargs):
        return type("Out", (), {"claims": []})()

    engines = CompilerEngines(
        name="test-provider", extract=ok, structure=ok, submit_batch=ok, fetch_batch=ok
    )
    with _client(engines) as (client, _):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")

        # Whatever the chain concluded, it must stop saying "running" once it
        # has stopped running. A state that never leaves its first value is
        # worse than no state at all.
        for _ in range(200):
            body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()
            if body["state"] != "running":
                break
        assert body["state"] in ("complete", "stopped"), body


def test_a_second_compile_supersedes_the_first_rather_than_racing_it() -> None:
    """Pressing Compile twice is what an operator does when nothing happens.

    Two chains writing one engagement's bank is a race with no winner worth
    having, so the second attempt is what the screen reports either way.
    """

    with _client(_slow_engines()) as (client, _):
        engagement_id = _engagement(client)

        first = client.post(f"/api/engagements/{engagement_id}/bank/compile").json()["job_id"]
        second = client.post(f"/api/engagements/{engagement_id}/bank/compile").json()["job_id"]

        assert first != second
        assert client.get(f"/api/engagements/{engagement_id}/bank/compile").json()[
            "compile_id"
        ] == second


def test_a_compile_that_crashes_still_leaves_a_record() -> None:
    """Moving the work out of the request took its failures with it.

    An exception used to travel back up the request as a 500 — ugly, and
    visible. Running in the background, it went nowhere: no run was stored, so
    the outcome route answered 404 and the screen said "Not compiled yet"
    about a compile that had just fallen over. That is the same silence this
    whole route exists to end, reintroduced by the fix for a different one.
    """

    async def boom(*_args, **_kwargs):
        raise RuntimeError("something in this codebase is broken")

    engines = CompilerEngines(
        name="test-provider", extract=boom, structure=boom, submit_batch=boom, fetch_batch=boom
    )
    with _client(engines) as (client, _):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")

        for _ in range(400):
            response = client.get(f"/api/engagements/{engagement_id}/bank/compile")
            if response.status_code == 200 and response.json()["state"] != "running":
                break
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "stopped", body
        # Not a provider problem, and it must not be dressed as one.
        assert body["cause"] == "failed", body


def test_a_crash_between_the_passes_is_recorded_too() -> None:
    """The gap the test above does not cover, found by tripping over it.

    Each pass wraps its own chain and persists a FAILED record, so a stage that
    raises is already accounted for. Nothing wrapped the *orchestration* around
    them — and a fetch returning the wrong shape blew up inside collection,
    took the background task with it, and left the outcome route answering 404
    as though no compile had ever been asked for.

    While the work ran inside the request this surfaced as a 500. Moving it out
    made it silent, which is worse.
    """

    async def ok(*_args, **_kwargs):
        return type("Out", (), {"claims": [], "candidates": []})()

    async def wrong_shape(*_args, **_kwargs):
        return object()  # not iterable, and collection will try to iterate it

    engines = CompilerEngines(
        name="test-provider",
        extract=ok,
        structure=ok,
        submit_batch=ok,
        fetch_batch=wrong_shape,
    )
    with _client(engines) as (client, _):
        engagement_id = _engagement(client)
        client.post(f"/api/engagements/{engagement_id}/bank/compile")

        for _ in range(400):
            response = client.get(f"/api/engagements/{engagement_id}/bank/compile")
            if response.status_code == 200 and response.json()["state"] != "running":
                break
        assert response.status_code == 200, (
            "the compile crashed and the screen was told nothing had been tried"
        )
        assert response.json()["state"] == "stopped", response.text
