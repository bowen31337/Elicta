"""Drafting the bank when the credential cannot use the Batch API.

The Analyst pass is submitted as a batch because it is cheap and there is no
hurry — the pass runs in minutes and nobody is waiting on it. That is an
optimisation, and it was also the only path: a token without `user:batch` was
refused at submission, and the bank stayed empty for ever no matter how many
times the operator pressed Compile.

The same pass runs perfectly well as an ordinary request. It costs more and
finishes in one visit instead of two, which for somebody who cannot submit a
batch at all is a trade with only one side.

Only an *entitlement* refusal falls back. A provider that is merely unreachable
will refuse the direct call for the same reason it refused the batch, and
trying it anyway spends a second round trip to learn what the first already
said.
"""

from __future__ import annotations

import contextlib

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.compiler.agent.bmad_analyst import MIN_CANDIDATES
from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
)
from app.orchestration.engines import (
    CompilerEngines,
    UpstreamFailure,
    UpstreamUnavailableError,
)

from conftest import configured_settings_store, fake_microsoft


def _candidate(index: int) -> dict:
    return {
        "template_section": "volumes",
        "trigger_types": ["unquantified-quantity"],
        "phrasing": f"How many consignments a month, question {index}?",
        "stub": f"How many, exactly? ({index})",
        "lang": "en",
        "priority": index,
    }


async def _ok(*_args, **_kwargs):
    """A stage that succeeds and produces nothing.

    Both fields because the two passes read different ones, and this stands in
    for both — an empty document set is a perfectly good input here, since what
    is under test is which route the *Analyst* pass takes, not what it finds.
    """

    return type("Out", (), {"claims": [], "candidates": []})()


def _analyst_output(count: int = MIN_CANDIDATES) -> BmadAnalystPassOutput:
    """A pass that satisfies the 150-300 contract the collection enforces.

    Not an arbitrary number: a pass outside that range is rejected wherever it
    came from, so a fallback producing five candidates would look like it
    worked and be thrown away. It is also the reason the direct route is not
    free — a hundred and fifty drafted questions is a large answer to ask for
    in one ordinary request.
    """

    return BmadAnalystPassOutput(candidates=[_candidate(i + 1) for i in range(count)])


def _engines(
    *,
    submit_failure: UpstreamFailure | None,
    with_direct: bool,
    direct_failure: UpstreamFailure | None = None,
) -> CompilerEngines:
    async def submit_batch(*_args, **_kwargs):
        if submit_failure is not None:
            raise UpstreamUnavailableError(
                "batch submission", submit_failure, "the provider refused."
            )
        return "batch-1"

    async def run_analyst(engagement_id: str, _context_pack):
        if direct_failure is not None:
            raise UpstreamUnavailableError(
                "analyst pass", direct_failure, "the provider refused."
            )
        return [AnalystBatchResult(custom_id=engagement_id, output=_analyst_output())]

    async def fetch_batch(_job_id: str):
        return [AnalystBatchResult(custom_id="eng-1", output=_analyst_output())]

    return CompilerEngines(
        name="test-provider",
        extract=_ok,
        structure=_ok,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
        run_analyst=run_analyst if with_direct else None,
    )


@contextlib.contextmanager
def _client(engines: CompilerEngines):
    backend = Backend()
    app = build_app(
        backend,
        compiler_engines=engines,
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    with TestClient(app) as client:
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


def _compile_and_settle(client: TestClient, engagement_id: str) -> dict:
    client.post(f"/api/engagements/{engagement_id}/bank/compile")
    for _ in range(400):
        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()
        if body.get("state") != "running":
            return body
    raise AssertionError("the compile never stopped running")


def test_a_bank_is_drafted_even_though_the_batch_was_refused() -> None:
    with _client(
        _engines(submit_failure=UpstreamFailure.NOT_ENTITLED, with_direct=True)
    ) as (client, _):
        engagement_id = _engagement(client)
        _compile_and_settle(client, engagement_id)

        bank = client.get(f"/api/engagements/{engagement_id}/bank").json()

        assert bank["sections"], "the bank is still empty"
        assert bank["sections"][0]["candidates"], bank


def test_the_run_says_it_took_the_direct_route_rather_than_hiding_it() -> None:
    """Cost changed, so the record has to show it.

    A fallback that leaves no trace is one nobody can audit the spend of, and
    "why is this engagement more expensive than that one" would have no answer.
    """

    with _client(
        _engines(submit_failure=UpstreamFailure.NOT_ENTITLED, with_direct=True)
    ) as (client, _):
        engagement_id = _engagement(client)
        outcome = _compile_and_settle(client, engagement_id)

        assert outcome["state"] == "complete", outcome
        assert "analyst-pass-direct" in outcome["stages_completed"], outcome
        assert "batch-submission" not in outcome["stages_completed"], outcome


def test_a_provider_that_is_merely_unreachable_is_reported_once() -> None:
    """One account of one failure, at the stage that actually ran.

    Rewritten when the app stopped sending a batch for a compile somebody is
    waiting on — measured against the provider, every batch that succeeded
    took longer than any window worth making them wait, so waiting first and
    drafting directly anyway was the slowest and dearest of the routes.

    What the test is about survives that: a provider that cannot be reached
    answers the same way twice, so it is asked once, and the stage named is
    the one that was tried.
    """

    with _client(
        _engines(
            submit_failure=None,
            with_direct=True,
            direct_failure=UpstreamFailure.UNAVAILABLE,
        )
    ) as (client, _):
        engagement_id = _engagement(client)
        outcome = _compile_and_settle(client, engagement_id)

    assert outcome["stopped_at"] == "analyst-pass-direct", outcome
    assert outcome["cause"] == "unavailable", outcome


def test_the_compile_somebody_is_waiting_on_drafts_directly() -> None:
    """No batch, because no batch was ever going to arrive in time.

    Measured against the provider after the schema fix, the batches that
    *succeeded* took 202s, 307s and 501s. Waiting a bounded time for one and
    then drafting directly anyway spent the wait, spent a second pass, and
    still paid for the batch when it finished.

    The batch route itself is untouched and still the library's default; this
    is only what the button sends.
    """

    with _client(_engines(submit_failure=None, with_direct=True)) as (client, _):
        engagement_id = _engagement(client)
        outcome = _compile_and_settle(client, engagement_id)

    assert outcome["complete"] is True, outcome
    assert "analyst-pass-direct" in outcome["stages_completed"], outcome
    assert "batch-submission" not in outcome["stages_completed"], outcome



def test_a_direct_attempt_that_fails_is_not_reported_as_never_attempted() -> None:
    """The first version of this fallback hid its own errors.

    A refused batch and a direct route that then failed both reported
    "stopped at batch-submission" with the batch's refusal as the reason — so
    the second attempt left no trace, and against a real credential it looked
    exactly as though the fallback had never run. It had; it was failing, and
    the message saying why was thrown away.
    """

    async def submit_batch(*_args, **_kwargs):
        raise UpstreamUnavailableError(
            "batch submission", UpstreamFailure.NOT_ENTITLED, "no batch scope."
        )

    async def run_analyst(*_args, **_kwargs):
        raise UpstreamUnavailableError(
            "analyst pass", UpstreamFailure.UNAVAILABLE, "the provider timed out."
        )

    engines = CompilerEngines(
        name="test-provider",
        extract=_ok,
        structure=_ok,
        submit_batch=submit_batch,
        fetch_batch=_ok,
        run_analyst=run_analyst,
    )
    with _client(engines) as (client, _):
        engagement_id = _engagement(client)
        outcome = _compile_and_settle(client, engagement_id)

        assert outcome["stopped_at"] == "analyst-pass-direct", outcome
        assert "timed out" in (outcome["reason"] or ""), outcome
        assert outcome["cause"] == "unavailable", outcome
