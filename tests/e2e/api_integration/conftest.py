"""Fixtures for the API integration suite.

The app assembly itself lives in `app.composition` — this suite drives the
production composition root rather than a copy of it, which is what keeps
the two from drifting apart.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.composition import Backend, build_app

__all__ = ["Backend", "build_app"]


@pytest.fixture
def backend() -> Backend:
    return Backend()


@pytest.fixture
def app(backend: Backend) -> FastAPI:
    return build_app(backend)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
