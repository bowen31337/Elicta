"""Tests for the HTTP surface that writes one citation row to a session's citations table (PRD FR-8.7)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.pipeline.models import CitationRow, ClaimKind
from app.modules.debrief.pipeline.router import build_citation_row_router


def make_client() -> tuple[TestClient, list[CitationRow]]:
    saved: list[CitationRow] = []

    async def save(row: CitationRow) -> None:
        saved.append(row)

    app = FastAPI()
    app.include_router(build_citation_row_router(save))
    return TestClient(app), saved


def valid_payload(**overrides: object) -> dict:
    payload = {
        "session_id": "session-1",
        "claim_kind": ClaimKind.DECISION.value,
        "claim_index": 0,
        "utterance_id": "utt-1",
        "start_seconds": 0.0,
        "end_seconds": 1.0,
        "speaker_tag": "alice",
        "quoted_text": "we need this by friday",
        "original_language": "en",
        "translated_text": None,
    }
    payload.update(overrides)
    return payload


def test_writing_a_citation_row_with_a_real_utterance_id_persists_it():
    client, saved = make_client()

    response = client.post("/api/sessions/session-1/citations", json=valid_payload())

    assert response.status_code == 201
    assert response.json()["utterance_id"] == "utt-1"
    assert len(saved) == 1
    assert saved[0].utterance_id == "utt-1"


def test_writing_a_citation_row_with_a_null_utterance_id_returns_422_with_an_error_message():
    client, saved = make_client()

    response = client.post("/api/sessions/session-1/citations", json=valid_payload(utterance_id=None))

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert any("utterance_id" in str(error.get("loc", "")) for error in body["detail"])
    assert saved == []


def test_writing_a_citation_row_missing_utterance_id_entirely_returns_422():
    payload = valid_payload()
    del payload["utterance_id"]
    client, saved = make_client()

    response = client.post("/api/sessions/session-1/citations", json=payload)

    assert response.status_code == 422
    assert saved == []
