"""Journey 5 is called "When the connection drops", and could not detect one.

The panel's mode comes from the stream's first `lane` frame, and `_lane_status`
decided it by asking the engines whether they are *configured* — a property
fixed when the app was built. A provider outage, an expired credential, a
throttled deployment and a revoked scope all leave it saying `model_reachable:
True`, so the panel keeps promising the slow lane while every call across it is
failing.

That is the exact failure the journey says it exists to prevent: the operator
reads a quiet panel as "nothing worth asking" when the truth is "nothing is
getting through". Silence has to be unambiguous, and it can only be that if the
mode is read from what actually happened on the wire.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import (
    DebriefEngines,
    UpstreamFailure,
    UpstreamUnavailableError,
)

from conftest import configured_settings_store, fake_microsoft


def _lane(client: TestClient, meeting_id: str) -> dict:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        body = "".join(response.iter_text())

    name = None
    for line in body.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name == "lane":
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"no lane frame in the stream:\n{body}")


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind",
            "sector": "Freight",
            "commercial_context": "Depot discovery",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "line-in"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _engines(failure: UpstreamFailure | None) -> DebriefEngines:
    """Engines that are configured, and either answer or fail like a provider."""

    async def stage(*_args, **_kwargs):
        if failure is not None:
            raise UpstreamUnavailableError("a stage", failure, "the provider said no.")
        # Shaped as content blocks because `converse` is the stage these tests
        # drive, and the session router validates what comes back.
        return [{"type": "text", "text": "nothing changed."}]

    return DebriefEngines(
        name="test-provider",
        diarize=stage,
        clean=stage,
        translate=stage,
        classify=stage,
        run_chain=stage,
        converse=stage,
    )


def _client(engines: DebriefEngines) -> tuple[TestClient, Backend]:
    backend = Backend()
    app = build_app(
        backend,
        debrief_engines=engines,
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    return TestClient(app), backend




def test_a_configured_provider_that_answers_reads_as_reachable() -> None:
    client, _ = _client(_engines(None))

    assert _lane(client, _meeting(client))["model_reachable"] is True


@pytest.mark.parametrize(
    ("failure", "expected_phrase"),
    [
        (UpstreamFailure.UNAVAILABLE, "could not be reached"),
        (UpstreamFailure.RATE_LIMITED, "throttling"),
        (UpstreamFailure.CREDENTIAL_REJECTED, "refused"),
        (UpstreamFailure.NOT_ENTITLED, "not permitted"),
    ],
)
def test_a_provider_that_fails_puts_the_panel_into_degraded_mode(
    failure: UpstreamFailure, expected_phrase: str
) -> None:
    """Each failure names its own remedy.

    Collapsing them into "the model is unreachable" would send an operator
    looking for a network problem when the credential was revoked — the
    distinction the failure taxonomy exists to preserve, thrown away one layer
    from the person who needs it.
    """

    client, backend = _client(_engines(failure))
    meeting_id = _meeting(client)

    # A real turn across the seam, which is what proves the connection is down.
    # The debrief conversation is used because it is a genuine provider call:
    # `/slow-lane/tick` records a tick and reaches no model at all.
    client.post(f"/api/meetings/{meeting_id}/debrief/start")
    response = client.post(
        f"/api/meetings/{meeting_id}/debrief/message", json={"message": "what changed?"}
    )
    assert response.status_code in (429, 503), response.text

    lane = _lane(client, meeting_id)
    assert lane["model_reachable"] is False
    assert expected_phrase in (lane["reason"] or "").lower(), lane["reason"]


def test_the_panel_is_not_told_the_lane_is_down_before_anything_was_tried() -> None:
    """An untried provider is unproven, not broken.

    Showing "Deterministic only" on a healthy meeting that simply has not
    needed the slow lane yet would train the operator to ignore the badge,
    which costs more than it saves.
    """

    client, _ = _client(_engines(UpstreamFailure.UNAVAILABLE))

    assert _lane(client, _meeting(client))["model_reachable"] is True


def test_an_unconfigured_provider_still_says_so() -> None:
    """The case that already worked, kept working."""

    client, _ = _client(DebriefEngines.unconfigured())
    lane = _lane(client, _meeting(client))

    assert lane["model_reachable"] is False
    assert "Settings" in (lane["reason"] or "")


def test_the_debrief_conversation_leaves_an_egress_row() -> None:
    """The same bypass, seen from the other side.

    The lane never went down because the debrief conversation called
    `debrief_engines.converse` directly instead of the wrapped seam — and that
    wrapper is also the audited chokepoint (NFR-2.7). So the one call that
    sends a client's transcript to a provider so the operator can ask questions
    about it was the one call leaving no record of having done so.

    "Single audited chokepoint" is only true if everything goes through it.
    """

    client, backend = _client(_engines(None))
    meeting_id = _meeting(client)

    client.post(f"/api/meetings/{meeting_id}/debrief/start")
    client.post(f"/api/meetings/{meeting_id}/debrief/message", json={"message": "what changed?"})

    assert backend.egress_rows, "the conversation reached a provider and recorded nothing"


def test_a_compiler_failure_does_not_report_the_live_lane_as_down() -> None:
    """The badge speaks only for the engines it reports on.

    `_lane_status` asks the *debrief* engines whether they are configured, so
    only calls across those seams may decide what it says. The compiler is a
    different workload on a different entitlement: drafting the question bank
    is a batch job, and a plan can permit live messages while refusing batches
    — which is exactly the credential this repository is exercised against.

    Observing both into one place put a live run's panel into degraded mode
    because a *pre-meeting* compile had been refused for want of a batch scope,
    about a model that was answering fine. The live harness caught it: journey
    5's "not falsely claiming degraded mode" check went red the first time this
    ran end to end.
    """

    from app.orchestration.engines import CompilerEngines

    async def refused(*_args, **_kwargs):
        raise UpstreamUnavailableError(
            "batch submission",
            UpstreamFailure.NOT_ENTITLED,
            "OAuth token does not meet scope requirement any_of(user:batch, ...).",
        )

    backend = Backend()
    app = build_app(
        backend,
        debrief_engines=_engines(None),
        compiler_engines=CompilerEngines(
            name="test-provider",
            extract=refused,
            structure=refused,
            submit_batch=refused,
            fetch_batch=refused,
        ),
        settings_store=configured_settings_store(),
        document_transport=fake_microsoft,
    )
    client = TestClient(app)
    meeting_id = _meeting(client)
    engagement_id = client.get(f"/api/meetings/{meeting_id}").json()["engagement_id"]

    client.post(f"/api/engagements/{engagement_id}/bank/compile")

    assert _lane(client, meeting_id)["model_reachable"] is True, (
        "a refused batch submission is not evidence about the live slow lane"
    )
