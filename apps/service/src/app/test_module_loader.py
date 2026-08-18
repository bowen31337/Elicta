"""Tests for the startup module-router scanner."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app import module_loader


class _FakeModuleInfo:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ispkg = True


@pytest.fixture
def fake_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str, types.ModuleType | None], None]:
    """Register fake `app.modules.<name>` entries for one test, then clean up."""

    created: list[str] = []

    def register(name: str, module: types.ModuleType | None) -> None:
        if module is not None:
            sys.modules[f"{module_loader.MODULES_PACKAGE}.{name}"] = module
        created.append(name)

    def fake_iter_modules(_path: object) -> list[_FakeModuleInfo]:
        return [_FakeModuleInfo(name) for name in created]

    monkeypatch.setattr(module_loader.pkgutil, "iter_modules", fake_iter_modules)
    yield register

    for name in created:
        sys.modules.pop(f"{module_loader.MODULES_PACKAGE}.{name}", None)


def test_mounts_a_module_that_exposes_a_router(fake_modules) -> None:
    router = APIRouter(prefix="/api/widgets", tags=["widgets"])

    @router.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    module = types.ModuleType("app.modules.widgets")
    module.router = router
    fake_modules("widgets", module)

    app = FastAPI()
    mounted = module_loader.load_modules(app)

    assert len(mounted) == 1
    assert mounted[0].module == "app.modules.widgets"
    assert mounted[0].prefix == "/api/widgets"
    assert mounted[0].tags == ("widgets",)

    response = TestClient(app).get("/api/widgets/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_mounts_every_router_from_a_module_exposing_routers(fake_modules) -> None:
    first = APIRouter(prefix="/api/a")
    second = APIRouter(prefix="/api/b")
    module = types.ModuleType("app.modules.multi")
    module.routers = [first, second]
    fake_modules("multi", module)

    app = FastAPI()
    mounted = module_loader.load_modules(app)

    assert {entry.prefix for entry in mounted} == {"/api/a", "/api/b"}


def test_skips_a_module_that_exposes_no_router(fake_modules) -> None:
    module = types.ModuleType("app.modules.no_router")
    fake_modules("no_router", module)

    app = FastAPI()
    mounted = module_loader.load_modules(app)

    assert mounted == []


def test_skips_a_module_that_fails_to_import(fake_modules) -> None:
    # No module registered in sys.modules for this name, so importlib tries
    # (and fails) to find a real `does_not_exist_on_disk` submodule on disk.
    fake_modules("does_not_exist_on_disk", None)

    app = FastAPI()
    mounted = module_loader.load_modules(app)

    assert mounted == []


def test_ignores_a_router_attribute_that_is_not_an_apirouter(fake_modules) -> None:
    module = types.ModuleType("app.modules.not_a_router")
    module.router = "not actually a router"
    fake_modules("not_a_router", module)

    app = FastAPI()
    mounted = module_loader.load_modules(app)

    assert mounted == []
