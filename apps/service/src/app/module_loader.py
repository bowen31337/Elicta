"""Startup-time discovery and mounting of feature routers.

Scans the `app.modules` package for direct subpackages and mounts whatever
`fastapi.APIRouter` each one exposes at its package root (`router`, or
`routers` for a module that mounts more than one). A feature registers
itself simply by exposing that attribute from `app/modules/<name>/__init__.py`
(or re-exporting it there from a submodule) — nothing here, or in the app
factory, needs to change when a module is added, renamed, or removed.

Modules that don't expose a router (support packages, or features not yet
wired to real dependencies) are skipped rather than treated as an error,
since `app/modules/*` may contain in-progress features. `app/core/*`
packages are deliberately out of scope: they need dependencies injected by
hand and are mounted explicitly by whoever owns that wiring, not scanned.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)

MODULES_PACKAGE = "app.modules"


@dataclass(frozen=True)
class MountedRouter:
    """Record of one router mounted from a module, for startup reporting."""

    module: str
    prefix: str
    tags: tuple[str, ...]


def _discover_module_names() -> list[str]:
    package = importlib.import_module(MODULES_PACKAGE)
    return sorted(
        info.name
        for info in pkgutil.iter_modules(package.__path__)
        if info.ispkg and not info.name.startswith("_")
    )


def _routers_from(module: object) -> list[APIRouter]:
    routers: list[APIRouter] = []

    single = getattr(module, "router", None)
    if isinstance(single, APIRouter):
        routers.append(single)

    for candidate in getattr(module, "routers", None) or []:
        if isinstance(candidate, APIRouter):
            routers.append(candidate)

    return routers


def load_modules(app: FastAPI) -> list[MountedRouter]:
    """Scan `app/modules/*`, mount each exposed router, and report what was mounted."""
    mounted: list[MountedRouter] = []

    for name in _discover_module_names():
        full_name = f"{MODULES_PACKAGE}.{name}"
        try:
            module = importlib.import_module(full_name)
        except ImportError:
            logger.warning("module_loader: %s failed to import, skipping", full_name)
            continue

        routers = _routers_from(module)
        if not routers:
            logger.info("module_loader: %s exposes no router, skipping", full_name)
            continue

        for router in routers:
            app.include_router(router)
            mounted.append(
                MountedRouter(
                    module=full_name,
                    prefix=router.prefix,
                    tags=tuple(str(tag) for tag in router.tags),
                )
            )

    return mounted
