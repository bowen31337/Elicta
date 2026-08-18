"""Tests for the debrief conversation HTTP surface (PRD FR-7.1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.session.models import DebriefConversationSession
from app.modules.debrief.session.router import build_debrief_session_router


def make_client(conversation_ref: str = "conv-1") -> tuple[TestClient, list[DebriefConversationSession]]:
    saved: list[DebriefConversationSession] = []

    async def open_conversation(meeting_id: str, session_id: str) -> str:
        return conversation_ref

    async def save(session: DebriefConversationSession) -> None:
        saved.append(session)

    app = FastAPI()
    app.include_router(build_debrief_session_router(open_conversation, save))
    return TestClient(app), saved


def test_starting_a_debrief_session_returns_201_with_an_open_session():
    client, _ = make_client()

    response = client.post("/api/meetings/meeting-1/debrief/start")

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert body["status"] == "open"
    assert body["session_id"]
    assert body["conversation_ref"] == "conv-1"


def test_starting_a_debrief_session_enables_streaming_with_no_length_cap_or_latency_budget():
    client, _ = make_client()

    response = client.post("/api/meetings/meeting-1/debrief/start")

    body = response.json()
    assert body["streaming_enabled"] is True
    assert body["length_cap"] is None
    assert body["latency_budget_seconds"] is None


def test_starting_a_debrief_session_persists_it():
    client, saved = make_client()

    client.post("/api/meetings/meeting-1/debrief/start")

    assert len(saved) == 1
    assert saved[0].meeting_id == "meeting-1"


def test_each_start_call_opens_a_new_session_with_a_distinct_session_id():
    client, _ = make_client()

    first = client.post("/api/meetings/meeting-1/debrief/start").json()
    second = client.post("/api/meetings/meeting-1/debrief/start").json()

    assert first["session_id"] != second["session_id"]
