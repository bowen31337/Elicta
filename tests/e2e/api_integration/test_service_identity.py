"""The service says which executable it is, so a shell can tell its own.

The desktop shell starts its bundled service only when nothing is already
answering on port 8000 -- a rule written so that a developer's `uvicorn`, or a
second window of the app, is left alone. A bare TCP connect is all it asked,
so *anything* on that port was adopted.

What that meant in practice: a copy of the app installed in /Applications two
days earlier had its service on the port, and every rebuild launched from the
build tree talked to it. A new panel against an old API, silently, with the
symptom appearing as endpoints that 404 for no reason anybody could reproduce
-- the same request answered 200 in-process against the same database.

A port is not an identity. This is.
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app.composition import Backend, build_app


def _client() -> TestClient:
    return TestClient(build_app(Backend()))


def test_the_service_names_the_executable_it_is_running_as():
    with _client() as client:
        body = client.get("/api/service/identity").json()

    assert body["executable"] == sys.executable
    assert isinstance(body["frozen"], bool)


def test_a_service_run_from_source_says_it_is_not_frozen():
    """Which is what tells a shell it is looking at a developer's service.

    Left alone deliberately: somebody running `uvicorn` in a terminal is on
    the port on purpose, and refusing to launch beside them would break the
    workflow the rule was written for.
    """

    with _client() as client:
        body = client.get("/api/service/identity").json()

    # `sys.frozen` is set by PyInstaller and by nothing else.
    assert body["frozen"] is False


def test_the_identity_is_answerable_before_anything_is_configured():
    """It is asked at launch, by a shell deciding whether to start a service.

    A route that needed a credential, a database or a compiled bank would be
    useless for that -- the moment it is asked is the moment least likely to
    have any of them.
    """

    with _client() as client:
        assert client.get("/api/service/identity").status_code == 200
