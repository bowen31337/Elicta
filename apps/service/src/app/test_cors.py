"""Which origins may talk to this service.

The desktop app used to be served by the same origin it called, through a
proxy, so nothing here needed saying. A packaged app is not: it serves its
page from the shell's own protocol and reaches the service across an origin
boundary. Without an answer to that, every read is discarded by the webview
and every write is refused before it is sent — the app reports "The service
could not be reached", which is exactly what it looks like from inside.

The list is exact origins and stays that way. This service has no
authentication and holds vendor credentials; the only thing standing between
it and any page a browser happens to open is which origins it answers. A
wildcard would hand that to every one of them, and `*` is the fix that
suggests itself when a build is failing and it is late.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.composition import Backend, build_app

TAURI = "tauri://localhost"


def _client() -> TestClient:
    return TestClient(build_app(Backend()))


def test_the_packaged_app_may_read() -> None:
    """A response the webview will not hand over is the same as no response."""

    answered = _client().get("/api/engagements", headers={"Origin": TAURI})

    assert answered.status_code == 200, answered.text
    assert answered.headers.get("access-control-allow-origin") == TAURI


def test_the_packaged_app_may_write() -> None:
    """Every write is JSON, and a JSON body is preflighted before it is sent.

    The preflight answered 405 — an OPTIONS nothing had routed — so creating a
    meeting, saving a setting or recording a disposition failed in the app
    without the request ever reaching a route.
    """

    preflight = _client().options(
        "/api/meetings",
        headers={
            "Origin": TAURI,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert preflight.status_code in (200, 204), preflight.text
    assert preflight.headers.get("access-control-allow-origin") == TAURI
    assert "POST" in preflight.headers.get("access-control-allow-methods", "")


def test_the_windows_shell_is_answered_too() -> None:
    """Tauri serves the page from a different origin per platform.

    macOS and Linux use the custom protocol; Windows uses a host under http.
    A list naming one of them ships an app that works on one platform, and the
    build for the other is where anybody finds out.
    """

    answered = _client().get(
        "/api/engagements", headers={"Origin": "http://tauri.localhost"}
    )

    assert answered.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_a_page_that_simply_asks_is_not_answered() -> None:
    """The guard that keeps this from being a hole.

    Any page a browser opens can send requests to a service on the loopback
    address. What stops one reading vendor credentials out of this one is that
    it does not answer for their origin — so the allowance has to be the two
    the shell actually uses, and nothing else.
    """

    answered = _client().get(
        "/api/engagements", headers={"Origin": "https://not-the-app.example"}
    )

    assert "access-control-allow-origin" not in answered.headers, (
        "this service answers for an origin that is not the app"
    )
