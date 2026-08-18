"""FastAPI application entrypoint.

Mounts every feature router discovered by `module_loader.load_modules`,
then emits the resulting route list as the app starts. That startup log is
the route table: there is no separate, hand-maintained list of mounted
routes for a feature to fall out of sync with.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.module_loader import MountedRouter, load_modules

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    mounted: list[MountedRouter] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not mounted:
            logger.info("startup: no feature routers mounted")
        for entry in mounted:
            logger.info(
                "startup: mounted %s -> %s (tags=%s)",
                entry.module,
                entry.prefix or "/",
                ", ".join(entry.tags) or "-",
            )
        logger.info("startup: %d feature router(s) mounted", len(mounted))
        yield

    app = FastAPI(title="Elicta Service", lifespan=lifespan)
    mounted.extend(load_modules(app))
    return app


app = create_app()
