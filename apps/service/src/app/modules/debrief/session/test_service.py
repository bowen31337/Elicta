"""Tests for opening a meeting's debrief conversation (PRD FR-7.1, FR-7.4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.modules.debrief.session.models import (
    DebriefConversationSession,
    DebriefMessageRole,
    DebriefSessionStatus,
    NudgeDisposition,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.service import (
    open_debrief_conversation,
    send_debrief_message,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


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

    before = datetime.now(UTC)
    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )
    after = datetime.now(UTC)

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


def test_opening_a_debrief_conversation_starts_with_an_empty_history():
    async def save(session: DebriefConversationSession) -> None:
        pass

    open_conversation, _ = make_open_conversation()
    load_nudge_signal, _ = make_load_nudge_signal()

    result = asyncio.run(
        open_debrief_conversation("meeting-1", open_conversation, load_nudge_signal, save)
    )

    assert result.history == []


def make_open_session(
    *, conversation_ref: str = "conv-1", history: list | None = None
) -> DebriefConversationSession:
    return DebriefConversationSession(
        session_id="session-1",
        meeting_id="meeting-1",
        conversation_ref=conversation_ref,
        status=DebriefSessionStatus.OPEN,
        streaming_enabled=True,
        length_cap=None,
        latency_budget_seconds=None,
        opened_at=FIXED,
        nudge_dispositions=[],
        history=history if history is not None else [],
    )


def make_load_session(session: DebriefConversationSession):
    requested: list[str] = []

    async def load_session(meeting_id: str) -> DebriefConversationSession:
        requested.append(meeting_id)
        return session

    return load_session, requested


def make_send_message(response_content: list[dict] | None = None):
    response_content = (
        response_content
        if response_content is not None
        else [{"type": "text", "text": "Here is a summary."}]
    )
    requested: list[tuple[str, str]] = []

    async def send_message(conversation_ref: str, message: str) -> list[dict]:
        requested.append((conversation_ref, message))
        return response_content

    return send_message, requested


def test_sending_a_debrief_message_appends_the_full_response_content_to_history():
    session = make_open_session()
    saved: list[DebriefConversationSession] = []

    async def save(updated: DebriefConversationSession) -> None:
        saved.append(updated)

    load_session, _ = make_load_session(session)
    response_content = [
        {"type": "text", "text": "Here is a summary."},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "budget"}},
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search"},
    ]
    send_message, _ = make_send_message(response_content)

    result = asyncio.run(
        send_debrief_message(
            "meeting-1", "What's the budget status?", load_session, send_message, save
        )
    )

    assert len(result.history) == 2
    assert result.history[0].role == DebriefMessageRole.USER
    assert result.history[1].role == DebriefMessageRole.ASSISTANT
    assert result.history[1].content == response_content
    assert saved == [result]


def test_sending_a_debrief_message_sends_on_the_session_conversation_ref():
    session = make_open_session(conversation_ref="vendor-conv-42")

    async def save(updated: DebriefConversationSession) -> None:
        pass

    load_session, _ = make_load_session(session)
    send_message, requested = make_send_message()

    asyncio.run(
        send_debrief_message("meeting-1", "What's next?", load_session, send_message, save)
    )

    assert requested == [("vendor-conv-42", "What's next?")]


def test_sending_a_debrief_message_appends_to_existing_history_rather_than_replacing_it():
    session = make_open_session()

    async def save(updated: DebriefConversationSession) -> None:
        pass

    load_session, _ = make_load_session(session)
    first_response = [{"type": "text", "text": "First answer."}]
    send_message, _ = make_send_message(first_response)

    after_first = asyncio.run(
        send_debrief_message("meeting-1", "First question", load_session, send_message, save)
    )

    load_session_again, _ = make_load_session(after_first)
    second_response = [{"type": "text", "text": "Second answer."}]
    send_message_again, _ = make_send_message(second_response)

    after_second = asyncio.run(
        send_debrief_message(
            "meeting-1", "Second question", load_session_again, send_message_again, save
        )
    )

    assert len(after_second.history) == 4
    assert after_second.history[1].content == first_response
    assert after_second.history[3].content == second_response


def test_sending_a_debrief_message_never_extracts_text_from_a_multi_block_response():
    session = make_open_session()

    async def save(updated: DebriefConversationSession) -> None:
        pass

    load_session, _ = make_load_session(session)
    response_content = [
        {"type": "thinking", "thinking": "reasoning about the budget..."},
        {"type": "text", "text": "The budget is confirmed."},
    ]
    send_message, _ = make_send_message(response_content)

    result = asyncio.run(
        send_debrief_message("meeting-1", "Is the budget confirmed?", load_session, send_message, save)
    )

    assert result.history[-1].content == response_content
    assert len(result.history[-1].content) == 2
