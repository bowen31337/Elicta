"""Tests for the app entrypoint: what it mounts, and what it reports.

The first test here is the one that matters. An earlier version asserted only
that a "feature router(s) mounted" line was emitted — which an app serving
*zero* routes satisfies, and did, for the whole time the composition root was
missing. A criterion the empty case passes cannot detect the empty case, so
these assert on quantity and reachability instead.
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_the_app_actually_serves_its_documented_api() -> None:
    """The app is assembled, not merely constructible.

    This fails if the composition root stops being called, if a router is
    dropped, or if the app is wired to something that mounts nothing.
    """

    app = create_app()

    paths = app.openapi()["paths"]
    api_paths = [path for path in paths if path.startswith("/api")]

    assert api_paths, "create_app must serve the feature API, not an empty app"
    assert len(api_paths) >= 40, (
        f"expected the full documented surface, got {len(api_paths)} paths"
    )


def test_every_mounted_route_is_reachable_rather_than_merely_declared() -> None:
    """A declared route that 404s at the router level is not mounted.

    Hitting one real endpoint proves the app dispatches into a router, which
    a schema-only check cannot establish.
    """

    client = TestClient(create_app())

    response = client.post(
        "/api/engagements",
        json={"client_name": "Acme Corp", "engagement_name": "Discovery"},
    )

    assert response.status_code != 404, "the engagements router is not dispatching"
    assert response.status_code in (201, 422), (
        f"unexpected status from a mounted router: {response.status_code}"
    )


def test_startup_reports_how_many_routers_and_routes_were_mounted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    with caplog.at_level(logging.INFO, logger="app.main"), TestClient(app):
        pass

    startup_lines = [
        record.message for record in caplog.records if "router(s) mounted" in record.message
    ]

    assert startup_lines, "startup must report what it mounted"

    # Parse the count rather than substring-matching it: "40 feature
    # router(s) mounted" contains "0 feature router(s) mounted".
    match = re.search(r"startup: (\d+) feature router\(s\) mounted", startup_lines[-1])
    assert match, f"unrecognised startup line: {startup_lines[-1]}"
    assert int(match.group(1)) > 0, "startup reported an empty app"


def test_startup_logs_the_prefix_of_every_module_loader_router(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app import main as main_module
    from app import module_loader

    fake_entry = module_loader.MountedRouter(
        module="app.modules.example", prefix="/api/example", tags=("example",)
    )
    monkeypatch.setattr(main_module, "load_modules", lambda app: [fake_entry])

    app = main_module.create_app()

    with caplog.at_level(logging.INFO, logger="app.main"), TestClient(app):
        pass

    assert any(
        "app.modules.example" in record.message and "/api/example" in record.message
        for record in caplog.records
    )
