"""Tests for opening a meeting's debrief conversation (PRD FR-7.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.debrief.session.models import DebriefConversationSession, DebriefSessionStatus
from app.modules.debrief.session.service import open_debrief_conversation

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_open_conversation(conversation_ref: str = "conv-1"):
    requested: list[tuple[str, str]] = []

    async def open_conversation(meeting_id: str, session_id: str) -> str:
        requested.append((meeting_id, session_id))
        return conversation_ref

    return open_conversation, requested


def test_opening_a_debrief_conversation_persists_an_open_session():
    saved: list[DebriefConversationSession] = []

    async def save(session: DebriefConversationSession) -> None:
        saved.append(session)

    open_conversation, _ = make_open_conversation()

    result = asyncio.run(
        open_debrief_conversation(
            "meeting-1", open_conversation, save, session_id="session-1", opened_at=FIXED
        )
    )

    assert result.session_id == "session-1"
    assert result.meeting_id == "meeting-1"
    assert result.status == DebriefSessionStatus.OPEN
    assert result.opened_at == FIXED
    assert saved == [result]


def test_opening_a_debrief_conversation_enables_streaming_with_no_length_cap_or_latency_budget():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()

    result = asyncio.run(open_debrief_conversation("meeting-1", open_conversation, save))

    assert result.streaming_enabled is True
    assert result.length_cap is None
    assert result.latency_budget_seconds is None


def test_opening_a_debrief_conversation_opens_the_underlying_streaming_conversation_for_this_meeting_and_session():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, requested = make_open_conversation(conversation_ref="vendor-conv-42")

    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, save, session_id="session-1")
    )

    assert requested == [("meeting-1", "session-1")]
    assert result.conversation_ref == "vendor-conv-42"


def test_session_id_defaults_to_a_generated_value_when_not_supplied():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()

    first = asyncio.run(open_debrief_conversation("meeting-1", open_conversation, save))
    second = asyncio.run(open_debrief_conversation("meeting-1", open_conversation, save))

    assert first.session_id
    assert second.session_id
    assert first.session_id != second.session_id


def test_opened_at_defaults_to_now_when_not_supplied():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()

    before = datetime.now(timezone.utc)
    result = asyncio.run(open_debrief_conversation("meeting-1", open_conversation, save))
    after = datetime.now(timezone.utc)

    assert before <= result.opened_at <= after
