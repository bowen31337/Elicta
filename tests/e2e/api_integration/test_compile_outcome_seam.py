"""Why the question bank is empty, said where the operator is looking.

`POST /bank/compile` answers 202 whatever happens next, and the bank endpoint
answers `{"sections": []}` whatever the reason. The reason has always been
recorded — `CompileRun.stopped_at` names the stage, and that stage's record
carries the provider's own sentence — and it went to the service log and
nowhere else.

An operator watching an empty bank had no way to learn any of it. A real one
compiled four times against a model their credential could not use, and the
screen said the same nothing each time.

Two different failures, two different fixes, and neither is "wait":
  * the model saved in Settings is one the credential may not use
  * the token cannot submit a batch job, which is what drafts the questions
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import (
    CompilerEngines,
    UpstreamFailure,
    UpstreamUnavailableError,
)

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


def _client(engines: CompilerEngines) -> tuple[TestClient, Backend]:
    backend = Backend()
    app = build_app(
        backend,
        compiler_engines=engines,
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    return TestClient(app), backend


def _refusing(failure: UpstreamFailure, detail: str) -> CompilerEngines:
    async def refuse(*_args, **_kwargs):
        raise UpstreamUnavailableError("a stage", failure, detail)

    return CompilerEngines(
        name="test-provider",
        extract=refuse,
        structure=refuse,
        submit_batch=refuse,
        fetch_batch=refuse,
    )


def test_an_engagement_that_never_compiled_is_not_reported_as_failed(
    client: TestClient,
) -> None:
    """"Not asked for yet" and "asked for and stopped" are different things.

    A failure notice on every engagement whose bank is simply still to be
    drafted is a notice nobody reads by the second week.
    """

    engagement_id = _engagement(client)

    assert client.get(f"/api/engagements/{engagement_id}/bank/compile").status_code == 404


def test_a_compile_that_stopped_names_the_stage_and_the_kind() -> None:
    client, _ = _client(
        _refusing(
            UpstreamFailure.RATE_LIMITED,
            "refused as rate limited but gave no time to retry after.",
        )
    )
    engagement_id = _engagement(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body["complete"] is False
    assert body["stopped_at"] == "extraction"
    assert body["cause"] == "rate_limited"


def test_a_token_without_the_batch_scope_is_told_apart_from_a_throttle() -> None:
    """The two failures a real credential actually meets, and they are not alike.

    One clears by itself and the other never will. An operator told "rate
    limited" about a missing scope waits for something that is not coming.
    """

    async def extract(*_args, **_kwargs):
        return type("Out", (), {"claims": []})()

    async def refuse(*_args, **_kwargs):
        raise UpstreamUnavailableError(
            "batch submission",
            UpstreamFailure.NOT_ENTITLED,
            "OAuth token does not meet scope requirement any_of(user:batch, ...).",
        )

    client, _ = _client(
        CompilerEngines(
            name="test-provider",
            extract=extract,
            structure=refuse,
            submit_batch=refuse,
            fetch_batch=refuse,
        )
    )
    engagement_id = _engagement(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    assert client.get(f"/api/engagements/{engagement_id}/bank/compile").json()[
        "cause"
    ] == "not_entitled"


def test_an_unconfigured_provider_says_so_rather_than_blaming_the_network() -> None:
    client, _ = _client(CompilerEngines.unconfigured())
    engagement_id = _engagement(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert body["cause"] == "not_configured"


def test_the_latest_attempt_is_the_one_reported() -> None:
    """An operator who changed a setting and tried again wants the new answer.

    Reporting the first attempt for ever would have this screen insisting on a
    problem the operator had already fixed.
    """

    client, backend = _client(
        _refusing(UpstreamFailure.RATE_LIMITED, "refused as rate limited.")
    )
    engagement_id = _engagement(client)
    client.post(f"/api/engagements/{engagement_id}/bank/compile")
    first = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    # The operator fixes the model; the next compile gets further.
    async def extract(*_args, **_kwargs):
        return type("Out", (), {"claims": []})()

    backend.compile_runs.clear()
    client.post(f"/api/engagements/{engagement_id}/bank/compile")
    second = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()

    assert first["compile_id"] != second["compile_id"]
    assert second["compile_id"].endswith("2")


def test_one_engagement_s_failure_is_not_reported_against_another() -> None:
    client, _ = _client(_refusing(UpstreamFailure.UNAVAILABLE, "could not be reached."))
    failed = _engagement(client)
    untouched = _engagement(client)
    client.post(f"/api/engagements/{failed}/bank/compile")

    assert client.get(f"/api/engagements/{untouched}/bank/compile").status_code == 404
