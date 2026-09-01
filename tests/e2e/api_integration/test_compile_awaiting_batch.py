"""A compile waiting on its batch is not a compile that stopped.

Driven against the real chain with stub engines, this is what a successful
compile does:

    [ 0s] state='running'  stages=[]
    [12s] state='running'  stages=['extraction']
    [39s] state='running'  stages=['extraction','structuring','batch-submission']
    [42s] state='stopped'  stopped_at='batch-collection'  reason=None

Nothing went wrong there. The Analyst pass is submitted as a batch and
collected minutes later -- `fetch_batch` returns `[]` while the provider is
still processing -- so the chain returning at `batch-collection` is the
designed halfway point, and `BankCollector` sweeps for it.

The operator was told, forty seconds after pressing Compile: "The last compile
stopped while collecting the drafted questions. Nothing was refused -- the
drafting itself did not produce a usable bank." Every clause of that is wrong
about a submission that had just succeeded, and it arrives while the provider
is still working.

The second half is worse because it is silent. `compile_runs` is a plain dict
and the collector sweeps it, so a restart before the batch comes back leaves
nothing to sweep: the batch is paid for, the bank never updates, and no screen
ever mentions it. Anthropic batches may take hours, which makes a restart
inside that window ordinary rather than exceptional.
"""

from __future__ import annotations

import contextlib

from fastapi.testclient import TestClient

from app.composition import Backend, build_app


@contextlib.contextmanager
def _client(url: str, **kwargs):
    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend, **kwargs)) as client:
        yield client, backend
    store.close()


def _engagement(client: TestClient) -> str:
    made = client.post(
        "/api/engagements",
        json={"client_organisation": "Batch", "sector": "s", "commercial_context": "c"},
    )
    return made.json()["engagement_id"]


class _SubmittedRun:
    """A compile that got as far as sending the drafting job off.

    `analyst_passes` empty is what "still processing" looks like: an
    unfinished batch collects nothing at all, so an empty list means come
    back and a non-empty one means this is as good as it gets. That is the
    same distinction `BankCollector._finished_badly` draws.
    """

    def __init__(self, engagement_id: str, passes: list | None = None) -> None:
        self.engagement_id = engagement_id
        self.batch_job_id = "batch-abc"
        self.stages_completed = ["extraction", "structuring", "batch-submission"]
        self.stopped_at = "batch-collection"
        self.complete = False
        self.analyst_passes = passes or []


class _FailedPass:
    """What `fetch_batch` returns for a request the provider refused."""

    status = "failed"
    error = "output_config.format.schema: For 'integer' type, property 'minimum' is not supported"


def _submitted(backend: Backend, engagement_id: str) -> None:
    """Register a compile that has sent its batch, as the service does.

    Both halves, because they answer different questions: the in-memory run is
    what this process is working on, and the durable row is the obligation to
    go back for a batch that outlives it.
    """

    from datetime import UTC, datetime

    from app.modules.compiler.api.models import PendingCompileBatch

    backend.bank_compiles.append((engagement_id, "compile-1"))
    backend.compile_runs["compile-1"] = _SubmittedRun(engagement_id)
    backend.pending_compile_batches["compile-1"] = PendingCompileBatch(
        compile_id="compile-1",
        engagement_id=engagement_id,
        batch_job_id="batch-abc",
        stages_completed=["extraction", "structuring", "batch-submission"],
        submitted_at=datetime.now(UTC),
    )


def test_awaiting_the_provider_is_not_reported_as_a_failure(tmp_path):
    """The one state a compile spends most of its life in."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body["state"] == "awaiting", (
        f"a submitted batch reported as {body['state']!r} — the screen then tells "
        "the operator the drafting produced no usable bank, forty seconds after "
        "it was sent off successfully"
    )
    assert body["complete"] is False
    assert body["stopped_at"] is None, "nothing stopped it; it is waiting"


def test_a_submitted_batch_is_still_there_after_a_restart(tmp_path):
    """Or nothing ever collects it, and the bank silently never updates."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

    with _client(url) as (client, backend):
        after = client.get(f"/api/engagements/{engagement_id}/bank/compile")

    assert after.status_code == 200, (
        "the batch was paid for and is now unreachable: the collector sweeps "
        "`compile_runs`, and a restart empties it"
    )
    assert after.json()["state"] == "awaiting"


def test_the_collector_goes_back_for_a_batch_it_did_not_submit(tmp_path):
    """The point of storing it at all.

    `BankCollector` sweeps the in-flight compiles. A batch may take hours, so
    a restart inside that window is ordinary — and the sweep found nothing to
    do, for a job that had already been paid for.
    """

    from app.composition import _compiles_to_sweep

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

    with _client(url) as (_client_after, backend):
        # A fresh process: nothing in flight, and one batch still owed.
        assert backend.compile_runs == {}

        sweeping = _compiles_to_sweep(backend)

        assert set(sweeping) == {"compile-1"}
        run = sweeping["compile-1"]
        # What `collect_engagement_compile` asks a run for at this point.
        assert run.engagement_id == engagement_id
        assert run.batch_job_id == "batch-abc"
        assert run.stopped_at == "batch-collection"
        assert run.stages_completed == ["extraction", "structuring", "batch-submission"]


def test_an_in_flight_run_is_not_shadowed_by_its_own_stored_row(tmp_path):
    """The same compile must be swept once, by the object doing the work."""

    from app.composition import _compiles_to_sweep

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

        sweeping = _compiles_to_sweep(backend)

    assert set(sweeping) == {"compile-1"}
    assert isinstance(sweeping["compile-1"], _SubmittedRun), (
        "the live run knows more than the row rebuilt from storage"
    )


def test_a_batch_that_ended_badly_is_not_reported_as_still_waiting(tmp_path):
    """The failure this file's own first fix introduced.

    "Stopped at batch-collection" covers two opposite situations: a batch the
    provider is still working on, and one that ended and returned nothing
    usable. Reporting both as `awaiting` told an operator whose batch had
    errored forty-six seconds in that the drafting job was with the provider
    and would come back on its own — for ever.

    The distinguishing fact is whether any pass came back at all. An
    unfinished batch collects nothing; a finished one collects something,
    even if that something is an error.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        backend.bank_compiles.append((engagement_id, "compile-1"))
        backend.compile_runs["compile-1"] = _SubmittedRun(
            engagement_id, passes=[_FailedPass()]
        )

        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body["state"] != "awaiting", (
        "the batch ended and returned an error; nothing is coming back"
    )
    assert body["stopped_at"] == "batch-collection"


def test_a_restored_batch_that_ends_badly_stops_saying_it_is_waiting(tmp_path):
    """Otherwise the obligation outlives the thing it was an obligation about.

    A batch restored from storage carries no passes — that is what makes it
    look like one still processing, correctly, until it is collected. When
    collection brings back an error, two things have to happen: the row stops
    being owed, and the outcome stops reporting `awaiting`. Neither did, so a
    batch that had already failed at the provider went on telling the operator
    it was on its way for the life of the deployment.
    """

    from app.composition import _collect_one_compile, _compiles_to_sweep
    from app.orchestration.engines import CompilerEngines

    from app.modules.compiler.agent.models import AnalystBatchResult

    async def fetch_batch(_job_id):
        # The shape `fetch_batch` really returns for a request the provider
        # refused — the schema complaint that made every compile hang.
        return [
            AnalystBatchResult(
                custom_id=engagement_id,
                output=None,
                error=(
                    "output_config.format.schema: For 'integer' type, "
                    "property 'minimum' is not supported"
                ),
            )
        ]

    async def unused(*_a, **_k):
        raise AssertionError("not reached")

    engines = CompilerEngines(
        name="stub",
        extract=unused,
        structure=unused,
        submit_batch=unused,
        fetch_batch=fetch_batch,
    )

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

    with _client(url) as (client, backend):
        run = _compiles_to_sweep(backend)["compile-1"]
        import asyncio

        asyncio.run(_collect_one_compile(backend, run, engines))

        assert backend.pending_compile_batches == {}, (
            "the batch ended; there is nothing left to go back for"
        )
        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body.get("state") != "awaiting", body
    assert body.get("stopped_at") == "batch-collection", (
        "and it must still say where it got to, not 404 as if nothing ran"
    )


def test_a_batch_restored_from_storage_can_be_aged(tmp_path):
    """SQLite hands back a naive datetime; the collector compares aware ones.

    `_expired` subtracts the submission time from now to decide whether to
    abandon a batch. Restored, `submitted_at` came back without a timezone —
    SQLite does not keep one — and the subtraction raised. The exception
    escaped `_visit`, which ends the *whole* sweep: one restored batch stopped
    every engagement's bank from ever being collected, which is how a compile
    came to take for ever.
    """

    from datetime import UTC, datetime

    from app.composition import _compiles_to_sweep

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

    with _client(url) as (_after, backend):
        run = _compiles_to_sweep(backend)["compile-1"]
        submitted_at = run.submission.requested_at

        assert submitted_at.tzinfo is not None, (
            "naive here, and the collector subtracts it from an aware `now()`"
        )
        # The comparison the collector actually makes.
        assert (datetime.now(UTC) - submitted_at).total_seconds() >= 0


def test_one_unswept_batch_does_not_end_the_sweep(tmp_path):
    """Every other engagement's bank is waiting on the same loop.

    The collector already says so about a provider failure and guards for it.
    Anything else raised out of a visit killed the pass — so a single bad
    record was enough to stop collection everywhere.
    """

    import asyncio

    from app.orchestration.bank_collector import BankCollector

    class _Exploding:
        engagement_id = "eng-boom"
        batch_job_id = "batch-boom"
        analyst_passes: list = []
        stages_completed: list = []
        stopped_at = "batch-collection"

        @property
        def submission(self):
            raise RuntimeError("this record cannot be read")

    reached: list[str] = []

    async def collect(run):
        reached.append(run.engagement_id)
        return run

    collector = BankCollector(
        runs=lambda: {"bad": _Exploding(), "good": _SubmittedRun("eng-good")},
        collect=collect,
    )

    outcomes = asyncio.run(collector.sweep())

    assert "eng-good" in reached, (
        "the healthy engagement was never visited: one bad record ended the pass"
    )
    assert any(o.engagement_id == "eng-boom" for o in outcomes), (
        "and the one that failed has to be reported, not swallowed"
    )


def test_a_collection_that_failed_says_why(tmp_path):
    """`batch-collection` read its reason off the *submission* record.

    Which succeeded — that is what makes it a collection failure rather than a
    submission one — so the reason was always `None` and the screen said the
    compile "stopped while collecting the drafted questions" with nothing
    after it. The account of what went wrong is on the pass that came back.
    """

    from app.modules.compiler.agent.models import AnalystBatchResult

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        backend.bank_compiles.append((engagement_id, "compile-1"))
        run = _SubmittedRun(engagement_id)
        run.analyst_passes = [
            AnalystBatchResult(
                custom_id=engagement_id,
                output=None,
                error="analyst pass produced 1 candidates, outside the accepted 10-300 range",
            )
        ]
        backend.compile_runs["compile-1"] = run

        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body["stopped_at"] == "batch-collection"
    assert body["reason"] is not None, "the pass said what was wrong and nothing read it"
    assert "10-300" in body["reason"]


def test_the_outcome_says_when_the_compile_began(tmp_path):
    """A meter cannot move within a stage without knowing how long it has been.

    The stages are the only thing the service reports, and they land twenty
    seconds and then two hundred seconds apart. A bar that can only step at
    those boundaries stands still for minutes at a time, which is the thing it
    exists to distinguish from being stuck.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        engagement_id = _engagement(client)
        _submitted(backend, engagement_id)

        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body.get("started_at"), body
