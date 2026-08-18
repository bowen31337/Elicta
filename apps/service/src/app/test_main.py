"""Tests for the app entrypoint emitting its mounted route list at startup."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_startup_logs_how_many_feature_routers_were_mounted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    with caplog.at_level(logging.INFO, logger="app.main"), TestClient(app):
        pass

    assert any(
        "feature router(s) mounted" in record.message for record in caplog.records
    )


def test_startup_logs_the_prefix_of_every_mounted_router(
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
