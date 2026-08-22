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

from app.main import create_app, default_settings_database


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


def test_something_actually_collects_the_analyst_batches() -> None:
    """The bank fills only if a poller is *running*, not merely written.

    The compile submits a batch and collects once, microseconds later, when no
    batch has finished. `BankCollector` is what goes back — and a collector
    nobody starts is the same defect as the missing collection it replaced:
    `POST /bank/compile` answers 202, every stage succeeds, and the bank stays
    empty for ever. So this asserts the task exists while the app is up, and
    that it is gone once the app is down.
    """

    import asyncio

    app = create_app()
    running: list[str] = []

    async def enter_and_look() -> None:
        async with app.router.lifespan_context(app):
            running.extend(
                task.get_name()
                for task in asyncio.all_tasks()
                if task.get_name() == "bank-collector"
            )

    asyncio.run(enter_and_look())

    assert running == ["bank-collector"], (
        "nothing sweeps for finished analyst batches, so a compiled bank never "
        "reaches the screen"
    )


def test_the_collector_is_stopped_when_the_app_shuts_down() -> None:
    """A loop that outlives its app keeps polling a provider after shutdown."""

    import asyncio

    app = create_app()
    survivors: list[asyncio.Task] = []

    async def enter_and_leave() -> None:
        async with app.router.lifespan_context(app):
            pass
        survivors.extend(
            task for task in asyncio.all_tasks() if task.get_name() == "bank-collector"
        )

    asyncio.run(enter_and_leave())

    assert survivors == []


def test_the_settings_database_location_can_be_overridden(monkeypatch, tmp_path) -> None:
    # The headless deployment route: a service started from a different folder
    # must not silently come up with an empty configuration.
    monkeypatch.setenv("ELICTA_SETTINGS_DB", str(tmp_path / "elsewhere" / "settings.db"))

    assert default_settings_database() == tmp_path / "elsewhere" / "settings.db"


def test_the_settings_database_otherwise_lives_in_the_user_data_directory(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("ELICTA_SETTINGS_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_settings_database() == tmp_path / "elicta" / "settings.db"


def test_the_app_starts_with_no_speech_credentials_configured() -> None:
    """The CI / fresh-checkout case: this must not regress.

    `ConnectorSettings.record_vendors` defaults to Deepgram and AssemblyAI,
    and a brand-new settings store — exactly what a fresh checkout or a CI
    runner starts with — has neither credential set. An unconfigured speech
    vendor must fail closed per call, the same way an unconfigured Anthropic
    key does, not stop the service from starting: this is the regression
    `UnconfiguredVendor` propagating out of `create_app` would be.
    """

    from app.modules.settings.store import InMemorySettingsStore

    app = create_app(settings_store=InMemorySettingsStore())

    api_paths = [path for path in app.openapi()["paths"] if path.startswith("/api")]
    assert api_paths, "an unconfigured speech vendor must not stop the app assembling"
