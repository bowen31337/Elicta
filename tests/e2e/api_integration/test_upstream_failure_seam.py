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
    PermissionDeniedError,
    RateLimitError,
)
from app.composition import Backend, build_app
from app.orchestration.engines import UpstreamFailure
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
    """A throttle that says when to come back. The provider sent a number, so
    there really is something to come back after, and 429 is the honest answer."""

    response = _ask(
        _client_raising(
            _status_error(RateLimitError, 429, "rate limited", **{"retry-after": "30"})
        )
    )

    assert response.status_code == 429, response.text
    detail = response.json()["detail"].lower()
    assert "rate" in detail, f"the answer does not name the cause: {detail!r}"


def test_a_429_with_no_retry_hint_is_not_answered_as_a_retryable_thing() -> None:
    """The same status code, and not the same situation.

    Anthropic answers 429 with no `retry-after` when the *model* is outside the
    credential's plan, and the identical request a second later is refused
    identically. Answering 429 invites a retry that cannot work — it told a
    real operator to wait out a problem that was never going to clear, and the
    compile they were watching failed four times.

    503 says "not now, and not your fault" without promising a retry helps.
    """

    response = _ask(_client_raising(_status_error(RateLimitError, 429, "rate limited")))

    assert response.status_code == 503, response.text
    assert "retry-after" not in response.headers
    detail = response.json()["detail"].lower()
    assert "settings" in detail, f"the answer does not name the fix: {detail!r}"


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


# --------------------------------------------------------------------------
# A refusal that neither waiting nor re-typing the credential can fix.
#
# A working OAuth token was reported to an operator as "rate limited — the
# same request should succeed shortly" and as "the provider rejected the
# credential. Re-enter it on the Settings screen". Neither was true: the model
# was one the plan did not include, and the Batch API needed a scope the token
# did not carry. Both remedies the product suggested were dead ends.
# --------------------------------------------------------------------------


def _scope_error() -> PermissionDeniedError:
    return PermissionDeniedError(
        "forbidden",
        response=httpx.Response(403, request=_REQUEST),
        body={
            "type": "error",
            "error": {
                "type": "permission_error",
                "message": (
                    "OAuth token does not meet scope requirement "
                    "any_of(user:batch, user:developer, workspace:developer, "
                    "workspace:inference)"
                ),
            },
        },
    )


def test_a_missing_scope_is_not_answered_as_a_rate_limit() -> None:
    response = _ask(_client_raising(_scope_error()))

    assert response.status_code != 429, "429 tells the operator to wait for ever"
    assert response.headers.get("retry-after") is None
    assert response.status_code == 503, response.text


def test_a_missing_scope_answers_with_the_scope_it_wanted() -> None:
    """The provider names the fix; the answer is worthless without it."""

    response = _ask(_client_raising(_scope_error()))

    assert "user:batch" in response.json()["detail"]


def test_a_rate_limit_with_no_retry_hint_does_not_promise_it_will_pass() -> None:
    """What a model outside the plan returns: 429, and no `retry-after`.

    Answering "should succeed shortly" sent an operator away to wait for
    something that never happened — the same request is refused identically a
    second later, and for ever.
    """

    response = _ask(_client_raising(_status_error(RateLimitError, 429, "rate limited")))

    detail = response.json()["detail"]
    assert "should succeed shortly" not in detail
    assert "Settings" in detail, f"nothing tells the operator what to change: {detail!r}"


def test_every_upstream_failure_has_an_http_answer() -> None:
    """A new failure kind must not become a 500 by omission.

    The mapping is a bare dict lookup inside an exception handler, so a member
    with no entry raises `KeyError` *while handling the error* — the operator
    gets "Internal Server Error" and the sentence naming the real cause is
    lost. That is the failure this whole module exists to prevent.
    """

    from app.composition import upstream_status_for

    for failure in UpstreamFailure:
        assert upstream_status_for(failure) is not None, failure
