"""Produce the service tier's OpenAPI schema for the api-client generator.

Primary path: import the real FastAPI app from ``app.main`` — the module
loader entrypoint that mounts every router under apps/service/src/app/modules
— and read its schema directly. No server needs to be running for this.

Fallback path: ``app.main`` does not exist yet on this branch (the module
loader ships as a separate workspace-scaffold feature). Assemble a
throwaway FastAPI app from the routers that exist today, wired with stub
callbacks, so the generator has a real schema to produce typed bindings
from in the meantime. This branch stops being exercised the moment
``app.main`` lands — the primary path takes over automatically.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SERVICE_SRC = Path(__file__).resolve().parents[3] / "apps" / "service" / "src"
sys.path.insert(0, str(SERVICE_SRC))


def _load_real_app():
    return importlib.import_module("app.main").app


def _load_fallback_app():
    from fastapi import FastAPI

    from app.core.consent import ConsentModel, build_consent_router
    from app.modules.engagement.api.router import build_engagement_router
    from app.modules.engagement.api.schemas import EngagementCreateRequest

    async def _get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return ConsentModel.PER_MEETING

    async def _is_confirmed_for_meeting(meeting_id: str) -> bool:
        return False

    async def _create_engagement(payload: EngagementCreateRequest) -> str:
        return "stub-engagement-id"

    app = FastAPI(title="Elicta Service", version="0.0.0")
    app.include_router(
        build_consent_router(_get_engagement_consent_model, _is_confirmed_for_meeting)
    )
    app.include_router(build_engagement_router(_create_engagement))
    return app


def main() -> None:
    try:
        app = _load_real_app()
    except ModuleNotFoundError:
        app = _load_fallback_app()

    schema = app.openapi()
    out_path = Path(__file__).resolve().parents[1] / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
