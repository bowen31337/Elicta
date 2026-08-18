"""Tests for deleting a bank candidate before its meeting (DELETE /api/bank/candidates/{id})."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.router import build_bank_candidates_router


def make_client(candidate_ids: set[str]) -> TestClient:
    deleted: list[str] = []

    async def delete_candidate(candidate_id: str) -> None:
        if candidate_id not in candidate_ids:
            raise CandidateNotFoundError(candidate_id)
        candidate_ids.discard(candidate_id)
        deleted.append(candidate_id)

    app = FastAPI()
    app.include_router(build_bank_candidates_router(delete_candidate))
    app.state.deleted = deleted
    return TestClient(app)


def test_delete_bank_candidate_returns_204_and_no_body():
    client = make_client({"c1"})

    response = client.delete("/api/bank/candidates/c1")

    assert response.status_code == 204
    assert response.content == b""
    assert client.app.state.deleted == ["c1"]


def test_delete_bank_candidate_for_unknown_candidate_returns_404():
    client = make_client({"c1"})

    response = client.delete("/api/bank/candidates/unknown")

    assert response.status_code == 404
    assert client.app.state.deleted == []
