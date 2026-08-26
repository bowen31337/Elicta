"""The debrief's output outlives the process that produced it.

Reported as "after restart the brief content is missing". `bmad_chains` is
what the project brief, the decision log, the open questions and the
follow-up email all read, and it was a plain dict — so a restart took every
one of them.

The record's own docstring calls it a "Durable record of one BMAD analyst
chain run". It was designed to be durable and never wired to anything, which
is the same classification error CLAUDE.md records for five other
collections: "rebuilt on demand" turning out to mean "lost on restart".

Nothing rebuilds this one either. It is a model pipeline over a whole
meeting's transcript, and it is the product's output rather than a cache of
it.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.composition import Backend, attach_state_store, build_app
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainStatus,
    SessionBmadAnalystChain,
)
from tests.e2e.api_integration.test_debrief import _artifact_set

_NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


@contextlib.contextmanager
def _client(url: str):
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend)) as client:
        yield client, backend
    store.close()


def _chain(session_id: str) -> SessionBmadAnalystChain:
    return SessionBmadAnalystChain(
        session_id=session_id,
        status=BmadAnalystChainStatus.COMPLETE,
        engine="claude",
        artifacts=_artifact_set(),
        requested_at=_NOW,
        completed_at=_NOW,
    )


def test_the_brief_is_still_there_after_a_restart(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (first, backend):
        backend.bmad_chains["s1"] = _chain("s1")
        assert first.get("/api/sessions/s1/project-brief").status_code == 200

    with _client(url) as (restarted, _):
        response = restarted.get("/api/sessions/s1/project-brief")

    assert response.status_code == 200, response.text
    assert response.json()["body"] == "brief"


def test_every_artifact_the_chain_carries_survives_with_it(tmp_path) -> None:
    """Four routes read one record, so losing it loses all four — and each is
    a different question an operator comes back for."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (first, backend):
        backend.bmad_chains["s1"] = _chain("s1")

    with _client(url) as (restarted, _):
        for path in (
            "/api/sessions/s1/project-brief",
            "/api/sessions/s1/decision-log",
            "/api/sessions/s1/open-questions",
            "/api/sessions/s1/follow-up-email",
        ):
            assert restarted.get(path).status_code == 200, path


def test_a_failed_run_is_still_distinguishable_from_one_never_made(tmp_path) -> None:
    """`status` and `error` exist so a failed debrief is visible rather than
    silent, and that distinction has to survive too — restored as a failure,
    not as a session nobody has run."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (first, backend):
        backend.bmad_chains["s2"] = SessionBmadAnalystChain(
            session_id="s2",
            status=BmadAnalystChainStatus.FAILED,
            engine="claude",
            artifacts=None,
            requested_at=_NOW,
            completed_at=_NOW,
            error="the provider refused",
        )

    with _client(url) as (restarted, backend):
        restored = backend.bmad_chains.get("s2")

    assert restored is not None, "a failed run came back as one never made"
    assert restored.status is BmadAnalystChainStatus.FAILED
    assert restored.error == "the provider refused"
