"""`GET /api/service/identity` — which executable is answering here.

The desktop shell starts its bundled service only when nothing is already
answering on its port, a rule written so a developer's `uvicorn` and a second
window of the app are both left alone. It asked with a bare TCP connect, so
anything at all on that port was adopted.

Observed: a copy of the app installed two days earlier held the port, and
every rebuild launched from the build tree talked to its service. A new panel
against an old API. The symptom was endpoints answering 404 that answered 200
in-process against the same database, which is about as confusing as a symptom
gets.

A port is not an identity. Answering that question is this route's whole job,
which is why it depends on nothing: no credential, no database, no bank. It is
asked at launch, when a deployment is least likely to have any of them.
"""

from __future__ import annotations

import sys

from fastapi import APIRouter
from pydantic import BaseModel


class ServiceIdentity(BaseModel):
    """Enough for a caller to tell "mine" from "somebody else's"."""

    #: The binary running this service. For a frozen build that is the sidecar
    #: inside the app bundle, which is exactly what the shell can compare
    #: against the one it was about to start.
    executable: str
    #: Whether this is a frozen single-file build (PyInstaller sets
    #: `sys.frozen`, and nothing else does) or a service run from source.
    #: A shell that finds a service run from source has found a developer.
    frozen: bool


router = APIRouter(prefix="/api/service", tags=["service"])


@router.get("/identity")
async def service_identity() -> ServiceIdentity:
    """Say which executable is answering, and whether it was frozen."""

    return ServiceIdentity(
        executable=sys.executable,
        frozen=bool(getattr(sys, "frozen", False)),
    )
