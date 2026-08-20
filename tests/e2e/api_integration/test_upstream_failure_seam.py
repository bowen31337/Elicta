"""An upstream rate limit is reported as a rate limit, not a 500.

The defect: `anthropic.RateLimitError` escaped the debrief conversation path
and FastAPI turned it into a bare 500 "Internal Server Error". The operator's
next move after a 429 and after a 500 are opposite — wait a minute, versus go
hunting for a broken deployment — so collapsing the two costs exactly the
information that decides it. The unconfigured case already got this right,
answering 503 and naming what was missing.

Every case here drives the production composition root and goes through the
API. The engine is the only thing faked, because the engine is the seam under
the API; the persistence the read path uses is real.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OverloadedError,
    RateLimitError,
)
from app.composition import Backend, build_app
from app.orchestration.anthropic_engines import anthropic_debrief_engines
from fastapi.testclient import TestClient

QUESTION = "Which requirements are still only inferred?"
_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(kind: type, status: int, message: str, **headers: str):
    return kind(
        message,
        response=httpx.Response(status, headers=headers, request=_REQUEST),
        body=None,
    )


class _FailingMessages:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def create(self, **_kwargs: Any) -> Any:
        raise self._error

    async def parse(self, **_kwargs: Any) -> Any:
        raise self._error


class _FailingClient:
    """An `AsyncAnthropic` whose every call fails the way `error` does."""

    def __init__(self, error: BaseException) -> None:
        self.messages = _FailingMessages(error)


def _client_raising(error: BaseException, **client_kwargs: Any) -> TestClient:
    """The production app, on the real engines, over a provider that fails.

    The fake is the *client*, not the engines. Faking the engines would skip
    `anthropic_engines`, which is where the translation this covers lives —
    the test would then assert only that the handler works, and the handler
    was never the missing part.
    """

    engines = anthropic_debrief_engines(_FailingClient(error))
    return TestClient(build_app(Backend(), debrief_engines=engines), **client_kwargs)


def _open_debrief(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Calder & Rowe",
            "sector": "professional services",
            "commercial_context": "Discovery for a matter-management replacement",
        },
    )
    assert engagement.status_code == 201, engagement.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": engagement.json()["engagement_id"], "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    meeting_id = meeting.json()["meeting_id"]

    started = client.post(f"/api/meetings/{meeting_id}/debrief/start")
    assert started.status_code == 201, started.text
    return meeting_id


def _ask(client: TestClient) -> httpx.Response:
    return client.post(
        f"/api/meetings/{_open_debrief(client)}/debrief/message", json={"message": QUESTION}
    )


def test_a_rate_limit_is_reported_as_a_rate_limit() -> None:
    response = _ask(_client_raising(_status_error(RateLimitError, 429, "rate limited")))

    assert response.status_code == 429, response.text
    detail = response.json()["detail"].lower()
    assert "rate" in detail, f"the answer does not name the cause: {detail!r}"


def test_a_rate_limit_passes_on_how_long_to_wait_when_the_provider_says() -> None:
    """"Wait" is only actionable with a number, and the provider sends one."""

    response = _ask(
        _client_raising(_status_error(RateLimitError, 429, "rate limited", **{"retry-after": "30"}))
    )

    assert response.headers.get("retry-after") == "30"


@pytest.mark.parametrize(
    ("error", "word"),
    [
        (APITimeoutError(request=_REQUEST), "timed out"),
        (APIConnectionError(request=_REQUEST), "reach"),
        (_status_error(OverloadedError, 529, "overloaded"), "overloaded"),
        (_status_error(InternalServerError, 500, "upstream boom"), "provider"),
    ],
    ids=["timeout", "connection", "overloaded", "upstream-5xx"],
)
def test_a_transient_provider_failure_is_not_a_500(error: BaseException, word: str) -> None:
    response = _ask(_client_raising(error))

    assert response.status_code == 503, response.text
    assert word in response.json()["detail"].lower(), response.text


def test_a_rejected_credential_says_so_rather_than_looking_like_an_outage() -> None:
    response = _ask(_client_raising(_status_error(AuthenticationError, 401, "bad key")))

    assert response.status_code == 503, response.text
    assert "credential" in response.json()["detail"].lower(), response.text


def test_a_malformed_request_is_still_ours_and_still_a_500() -> None:
    """The guard must not become a blanket except-everything.

    A 400 from the provider means *we* sent something wrong. That is a bug in
    this codebase, and a bug that answers 503 is a bug nobody investigates.
    """

    response = _ask(
        _client_raising(
            _status_error(BadRequestError, 400, "max_tokens exceeds model maximum"),
            raise_server_exceptions=False,
        )
    )

    assert response.status_code == 500, response.text


def test_a_plain_bug_in_a_stage_is_still_a_500() -> None:
    response = _ask(
        _client_raising(ZeroDivisionError("division by zero"), raise_server_exceptions=False)
    )

    assert response.status_code == 500, response.text


def test_a_refused_turn_leaves_no_assistant_turn_behind() -> None:
    """A 429 must not persist half a conversation for the panel to render."""

    client = _client_raising(_status_error(RateLimitError, 429, "rate limited"))
    meeting_id = _open_debrief(client)

    client.post(f"/api/meetings/{meeting_id}/debrief/message", json={"message": QUESTION})

    reopened = client.post(f"/api/meetings/{meeting_id}/debrief/start")
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["history"] == []
