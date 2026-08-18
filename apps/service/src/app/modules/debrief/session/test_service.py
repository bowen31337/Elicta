"""Tests for opening a meeting's debrief conversation (PRD FR-7.1, FR-7.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.debrief.session.models import (
    DebriefConversationSession,
    DebriefSessionStatus,
    NudgeDisposition,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.service import open_debrief_conversation

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_open_conversation(conversation_ref: str = "conv-1"):
    requested: list[tuple[str, str]] = []

    async def open_conversation(meeting_id: str, session_id: str) -> str:
        requested.append((meeting_id, session_id))
        return conversation_ref

    return open_conversation, requested


def make_load_nudge_signal(records: list[NudgeDispositionRecord] | None = None):
    records = records if records is not None else []
    requested: list[str] = []

    async def load_nudge_signal(meeting_id: str) -> list[NudgeDispositionRecord]:
        requested.append(meeting_id)
        return records

    return load_nudge_signal, requested


def make_nudge_record(
    nudge_id: str, disposition: NudgeDisposition, *, fired_at: datetime = FIXED
) -> NudgeDispositionRecord:
    return NudgeDispositionRecord(
        nudge_id=nudge_id,
        stub="Ask about budget",
        question="Did you confirm the budget with finance?",
        trigger_reason="Budget mentioned without a confirmed number",
        fired_at=fired_at,
        disposition=disposition,
    )


def test_opening_a_debrief_conversation_persists_an_open_session():
    saved: list[DebriefConversationSession] = []

    async def save(session: DebriefConversationSession) -> None:
        saved.append(session)

    open_conversation, _ = make_open_conversation()
    load_nudge_signal, _ = make_load_nudge_signal()

    result = asyncio.run(
        open_debrief_conversation(
            "meeting-1",
            open_conversation,
            load_nudge_signal,
            save,
            session_id="session-1",
            opened_at=FIXED,
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
    load_nudge_signal, _ = make_load_nudge_signal()

    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )

    assert result.streaming_enabled is True
    assert result.length_cap is None
    assert result.latency_budget_seconds is None


def test_opening_a_debrief_conversation_opens_the_underlying_streaming_conversation_for_this_meeting_and_session():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, requested = make_open_conversation(conversation_ref="vendor-conv-42")
    load_nudge_signal, _ = make_load_nudge_signal()

    result = asyncio.run(
        open_debrief_conversation(
            "meeting-1", open_conversation, load_nudge_signal, save, session_id="session-1"
        )
    )

    assert requested == [("meeting-1", "session-1")]
    assert result.conversation_ref == "vendor-conv-42"


def test_session_id_defaults_to_a_generated_value_when_not_supplied():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()
    load_nudge_signal, _ = make_load_nudge_signal()

    first = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )
    second = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )

    assert first.session_id
    assert second.session_id
    assert first.session_id != second.session_id


def test_opened_at_defaults_to_now_when_not_supplied():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()
    load_nudge_signal, _ = make_load_nudge_signal()

    before = datetime.now(timezone.utc)
    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )
    after = datetime.now(timezone.utc)

    assert before <= result.opened_at <= after


def test_opening_a_debrief_conversation_persists_every_nudge_disposition():
    saved: list[DebriefConversationSession] = []

    async def save(session: DebriefConversationSession) -> None:
        saved.append(session)

    open_conversation, _ = make_open_conversation()
    fired = make_nudge_record("nudge-1", NudgeDisposition.FIRED)
    taken = make_nudge_record("nudge-2", NudgeDisposition.TAKEN)
    parked = make_nudge_record("nudge-3", NudgeDisposition.PARKED)
    load_nudge_signal, requested = make_load_nudge_signal([fired, taken, parked])

    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )

    assert requested == ["meeting-1"]
    assert result.nudge_dispositions == [fired, taken, parked]
    assert saved[0].nudge_dispositions == [fired, taken, parked]


def test_opening_a_debrief_conversation_with_no_live_mode_nudges_persists_an_empty_list():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()
    load_nudge_signal, _ = make_load_nudge_signal([])

    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )

    assert result.nudge_dispositions == []
