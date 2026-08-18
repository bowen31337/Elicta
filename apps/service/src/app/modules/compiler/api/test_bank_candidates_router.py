"""Tests for deleting or patching a bank candidate before its meeting.

Covers `DELETE /api/bank/candidates/{id}` (returns 204) and `PATCH
/api/bank/candidates/{id}` (returns 200 with the updated candidate) --
edit, reorder, or prune a candidate.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.models import BankCandidate, CandidatePatchRequest
from app.modules.compiler.api.router import build_bank_candidates_router


def make_client(candidates: dict[str, BankCandidate]) -> TestClient:
    deleted: list[str] = []

    async def delete_candidate(candidate_id: str) -> None:
        if candidate_id not in candidates:
            raise CandidateNotFoundError(candidate_id)
        del candidates[candidate_id]
        deleted.append(candidate_id)

    async def update_candidate(candidate_id: str, patch: CandidatePatchRequest) -> BankCandidate:
        if candidate_id not in candidates:
            raise CandidateNotFoundError(candidate_id)
        updates = patch.model_dump(exclude_unset=True, exclude_none=True)
        candidates[candidate_id] = candidates[candidate_id].model_copy(update=updates)
        return candidates[candidate_id]

    app = FastAPI()
    app.include_router(build_bank_candidates_router(delete_candidate, update_candidate))
    app.state.deleted = deleted
    app.state.candidates = candidates
    return TestClient(app)


def make_candidate(candidate_id: str, **overrides: object) -> BankCandidate:
    defaults: dict[str, object] = {
        "id": candidate_id,
        "template_section": "scope",
        "phrasing": "who owns budget sign-off?",
        "priority": 1,
    }
    defaults.update(overrides)
    return BankCandidate(**defaults)


def test_delete_bank_candidate_returns_204_and_no_body():
    client = make_client({"c1": make_candidate("c1")})

    response = client.delete("/api/bank/candidates/c1")

    assert response.status_code == 204
    assert response.content == b""
    assert client.app.state.deleted == ["c1"]


def test_delete_bank_candidate_for_unknown_candidate_returns_404():
    client = make_client({"c1": make_candidate("c1")})

    response = client.delete("/api/bank/candidates/unknown")

    assert response.status_code == 404
    assert client.app.state.deleted == []


def test_patch_bank_candidate_edits_phrasing():
    client = make_client({"c1": make_candidate("c1")})

    response = client.patch("/api/bank/candidates/c1", json={"phrasing": "who signs off on budget?"})

    assert response.status_code == 200
    body = response.json()
    assert body["phrasing"] == "who signs off on budget?"
    assert body["priority"] == 1


def test_patch_bank_candidate_reorders_priority():
    client = make_client({"c1": make_candidate("c1", priority=3)})

    response = client.patch("/api/bank/candidates/c1", json={"priority": 1})

    assert response.status_code == 200
    assert response.json()["priority"] == 1


def test_patch_bank_candidate_prunes_it():
    client = make_client({"c1": make_candidate("c1")})

    response = client.patch("/api/bank/candidates/c1", json={"pruned": True})

    assert response.status_code == 200
    assert response.json()["pruned"] is True


def test_patch_bank_candidate_for_unknown_candidate_returns_404():
    client = make_client({"c1": make_candidate("c1")})

    response = client.patch("/api/bank/candidates/unknown", json={"phrasing": "new wording"})

    assert response.status_code == 404


def test_patch_bank_candidate_with_no_fields_returns_422():
    client = make_client({"c1": make_candidate("c1")})

    response = client.patch("/api/bank/candidates/c1", json={})

    assert response.status_code == 422
