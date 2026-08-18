"""Tests for the debrief conversation HTTP surface (PRD FR-7.1, FR-7.4)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.session.models import (
    DebriefConversationSession,
    DebriefSessionStatus,
    NudgeDisposition,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.router import build_debrief_session_router

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_client(
    conversation_ref: str = "conv-1",
    nudge_dispositions: list[NudgeDispositionRecord] | None = None,
    response_content: list[dict] | None = None,
    existing_session: DebriefConversationSession | None = None,
) -> tuple[TestClient, list[DebriefConversationSession]]:
    saved: list[DebriefConversationSession] = []
    nudge_dispositions = nudge_dispositions if nudge_dispositions is not None else []
    response_content = (
        response_content if response_content is not None else [{"type": "text", "text": "Reply."}]
    )

    async def open_conversation(meeting_id: str, session_id: str) -> str:
        return conversation_ref

    async def load_nudge_signal(meeting_id: str) -> list[NudgeDispositionRecord]:
        return nudge_dispositions

    async def save(session: DebriefConversationSession) -> None:
        saved.append(session)

    async def load_session(meeting_id: str) -> DebriefConversationSession:
        if existing_session is not None:
            return existing_session
        return DebriefConversationSession(
            session_id="session-1",
            meeting_id=meeting_id,
            conversation_ref=conversation_ref,
            status=DebriefSessionStatus.OPEN,
            streaming_enabled=True,
            length_cap=None,
            latency_budget_seconds=None,
            opened_at=FIXED,
            nudge_dispositions=[],
            history=[],
        )

    async def send_message(conversation_ref: str, message: str) -> list[dict]:
        return response_content

    app = FastAPI()
    app.include_router(
        build_debrief_session_router(
            open_conversation, load_nudge_signal, save, load_session, send_message
        )
    )
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


def test_starting_a_debrief_session_inherits_every_live_mode_nudge_disposition():
    dispositions = [
        NudgeDispositionRecord(
            nudge_id="nudge-1",
            stub="Ask about budget",
            question="Did you confirm the budget with finance?",
            trigger_reason="Budget mentioned without a confirmed number",
            fired_at=FIXED,
            disposition=NudgeDisposition.FIRED,
        ),
        NudgeDispositionRecord(
            nudge_id="nudge-2",
            stub="Ask about timeline",
            question="Did you confirm the go-live date?",
            trigger_reason="Timeline mentioned without a confirmed date",
            fired_at=FIXED,
            disposition=NudgeDisposition.TAKEN,
        ),
        NudgeDispositionRecord(
            nudge_id="nudge-3",
            stub="Ask about owner",
            question="Who owns this decision?",
            trigger_reason="Decision mentioned without a named owner",
            fired_at=FIXED,
            disposition=NudgeDisposition.PARKED,
        ),
    ]
    client, _ = make_client(nudge_dispositions=dispositions)

    response = client.post("/api/meetings/meeting-1/debrief/start")

    body = response.json()
    assert [record["disposition"] for record in body["nudge_dispositions"]] == [
        "fired",
        "taken",
        "parked",
    ]
    assert [record["nudge_id"] for record in body["nudge_dispositions"]] == [
        "nudge-1",
        "nudge-2",
        "nudge-3",
    ]


def test_starting_a_debrief_session_with_no_live_mode_nudges_returns_an_empty_list():
    client, _ = make_client(nudge_dispositions=[])

    response = client.post("/api/meetings/meeting-1/debrief/start")

    assert response.json()["nudge_dispositions"] == []


def test_sending_a_debrief_message_returns_200_with_the_updated_session():
    client, _ = make_client()

    response = client.post(
        "/api/meetings/meeting-1/debrief/message", json={"message": "What's the budget status?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "meeting-1"
    assert len(body["history"]) == 2


def test_sending_a_debrief_message_persists_the_full_response_content_in_history():
    response_content = [
        {"type": "text", "text": "Here is a summary."},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "budget"}},
    ]
    client, saved = make_client(response_content=response_content)

    response = client.post(
        "/api/meetings/meeting-1/debrief/message", json={"message": "What's the budget status?"}
    )

    body = response.json()
    assert body["history"][0]["role"] == "user"
    assert body["history"][1]["role"] == "assistant"
    assert body["history"][1]["content"] == response_content
    assert saved[-1].history[1].content == response_content
