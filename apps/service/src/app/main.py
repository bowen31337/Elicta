"""FastAPI application entrypoint.

Two things mount routers here, and they cover different cases:

* `app.composition.build_app` assembles every router whose factory needs
  persistence callables injected — which is nearly all of them. That is the
  composition root, and it is what the API integration suite drives.
* `app.module_loader.load_modules` scans `app/modules/*` for packages that
  expose an already-constructed router, for features that are self-sufficient
  and need no wiring.

Both report into the startup log, so that log remains the route table: there
is no separate, hand-maintained list of mounted routes for a feature to fall
out of sync with.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI

from app.composition import (
    Backend,
    attach_state_store,
    build_app,
    build_bank_collector,
    read_session_audio,
)
from app.module_loader import MountedRouter, load_modules
from app.modules.settings.models import SecretKey
from app.modules.settings.sqlite_store import SqliteSettingsStore
from app.modules.settings.store import SettingsStore
from app.orchestration.anthropic_engines import engines_from_settings
from app.orchestration.bank_collector import DEFAULT_INTERVAL_SECONDS
from app.orchestration.deepgram_engines import deepgram_diarizer
from app.orchestration.record_engines import build_record_engines, describe_record_engines
from app.persistence import open_state_store
from app.persistence.store import redact_database_url, resolve_database_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



def default_settings_database() -> Path:
    """Where operator settings are persisted.

    `ELICTA_SETTINGS_DB` overrides it; otherwise the file lives under the
    user's data directory rather than the working directory, so running the
    service from a different folder does not silently start it with an empty
    configuration.
    """

    configured = os.environ.get("ELICTA_SETTINGS_DB")
    if configured:
        return Path(configured)
    return Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / "elicta" / "settings.db"


def create_app(
    backend: Backend | None = None, settings_store: SettingsStore | None = None
) -> FastAPI:
    """Build the service.

    `backend` is the persistence surface every router is injected with. It
    defaults to the in-memory implementation so the app is runnable — and the
    full API reachable — without a database; a SQLAlchemy-backed `Backend`
    substitutes here and nowhere else.
    """

    # ADR-012: the compiler and debrief workloads run on Claude. Credentials
    # come from the settings store — administered in the desktop app's
    # settings screen, falling back to the environment for headless
    # deployments — and are re-read per call, so a key entered in the UI
    # takes effect without a restart. Until one is configured, the stages
    # that need a model fail closed and name what is missing; the service
    # still starts and serves its full API.
    store = settings_store or SqliteSettingsStore(default_settings_database())

    # G4: an engagement's memory has to outlive the process, so the backend
    # this function builds for itself is bound to the state database. A
    # caller that supplied its own `backend` is not second-guessed — that is
    # how the test suites inject a clean in-memory surface per test, and
    # attaching storage underneath them would silently share state between
    # tests that each expect to start empty.
    if backend is None:
        # Which database, decided the same way every other setting is: a URL
        # saved on the Settings screen wins, then `DATABASE_URL`, then the
        # SQLite file. Read before the store opens, because this chooses which
        # store to open.
        configured = store.get_secret(SecretKey.STATE_DATABASE_URL)
        database_url = resolve_database_url(configured.reveal() if configured else None)
        backend = attach_state_store(Backend(), open_state_store(database_url))
        logger.info("startup: state is durable in %s", redact_database_url(database_url))

    read_audio = read_session_audio(backend)
    debrief_engines, compiler_engines = engines_from_settings(
        store, diarize=deepgram_diarizer(read_audio, store)
    )

    # A selected vendor with no batch client at all (`UnconfiguredVendor`) is
    # a configuration error nothing can recover from while running, so that
    # still stops startup. A selected vendor missing only its credential does
    # not: like an unconfigured inference key elsewhere in this function, it
    # still gets an engine — one that fails closed, by name, the moment it is
    # called — so the service still starts and serves its full API. The
    # startup log says which is which, so the gap is visible immediately
    # rather than discovered from a `FAILED` transcript hours later.
    record_engines = build_record_engines(store, read_audio)
    logger.info(
        "startup: record path engines: %s",
        ", ".join(describe_record_engines(store)),
    )

    app = build_app(
        backend,
        debrief_engines=debrief_engines,
        compiler_engines=compiler_engines,
        settings_store=store,
        record_path_engines=record_engines,
    )
    mounted: list[MountedRouter] = load_modules(app)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Counted from the OpenAPI schema rather than `app.routes`: this
        # FastAPI version wraps included routers in `_IncludedRouter` objects
        # that carry no `.path`, so walking `app.routes` reports zero however
        # many routers are mounted.
        api_routes = [
            path for path in app.openapi()["paths"] if path.startswith("/api")
        ]

        for entry in mounted:
            logger.info(
                "startup: mounted %s -> %s (tags=%s)",
                entry.module,
                entry.prefix or "/",
                ", ".join(entry.tags) or "-",
            )
        logger.info(
            "startup: %d feature router(s) mounted, %d API route(s) served",
            len(mounted) + len(api_routes),
            len(api_routes),
        )

        # The Analyst pass is submitted as a batch and finishes minutes later.
        # Without something going back for it, `POST /bank/compile` answers 202,
        # every stage reports success and the question bank stays empty for
        # ever. This is the something. It belongs to the process rather than to
        # `build_app`, so a `TestClient` in the suites never starts a loop that
        # polls a provider nobody asked it to.
        collector = build_bank_collector(backend, compiler_engines)

        async def collect_forever() -> None:
            await collector.run(
                interval=DEFAULT_INTERVAL_SECONDS,
                sleep=asyncio.sleep,
                keep_going=lambda: True,
            )

        sweeper = asyncio.create_task(collect_forever(), name="bank-collector")
        logger.info(
            "startup: collecting analyst batches every %ss",
            int(DEFAULT_INTERVAL_SECONDS),
        )
        try:
            yield
        finally:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper

    app.router.lifespan_context = lifespan
    return app


app = create_app()
