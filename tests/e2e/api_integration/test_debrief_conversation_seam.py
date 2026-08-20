"""The debrief conversation answers from the model, or fails honestly.

The defect this covers: `send_debrief_message` in the composition root
returned a hardcoded `{"type": "text", "text": f"ack: {message}"}` and never
touched the engines `main.py` builds. On screen the operator saw Elicta reply
"ack: Which requirements are still only inferred?" — rendered identically to
a real answer. That inverts what this codebase promises: an unconfigured
deployment must fail honestly rather than look healthy.

Two cases, both through the API: unconfigured must refuse and say why, and
configured must return what the engine returned.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.composition import Backend, build_app
from app.orchestration.engines import DebriefEngines
from fastapi.testclient import TestClient

QUESTION = "Which requirements are still only inferred?"


def _open_debrief(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Calder & Rowe",
            "sector": "professional services",
            "commercial_context": "Discovery for a matter-management replacement",
        },
    )
    assert engagement.status_code == 201, engagement.text
    meeting = client.post(
        "/api/meetings",
        json={
            "engagement_id": engagement.json()["engagement_id"],
            "capture_mode": "live",
        },
    )
    assert meeting.status_code == 201, meeting.text
    meeting_id = meeting.json()["meeting_id"]

    started = client.post(f"/api/meetings/{meeting_id}/debrief/start")
    assert started.status_code == 201, started.text
    return meeting_id


def test_an_unconfigured_debrief_refuses_and_names_what_is_missing(
    client: TestClient,
) -> None:
    meeting_id = _open_debrief(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/debrief/message", json={"message": QUESTION}
    )

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "configured" in detail.lower(), f"the refusal does not say what is missing: {detail!r}"
    assert QUESTION not in detail


def test_an_unconfigured_debrief_never_writes_a_plausible_looking_answer(
    client: TestClient,
) -> None:
    """A refused turn must leave no assistant turn behind for the panel to render."""

    meeting_id = _open_debrief(client)

    client.post(f"/api/meetings/{meeting_id}/debrief/message", json={"message": QUESTION})

    # Re-open rather than read the backend: the session as the API reports it
    # is what the panel renders.
    reopened = client.post(f"/api/meetings/{meeting_id}/debrief/start")
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["history"] == []


@pytest.fixture
def recording_engines() -> tuple[DebriefEngines, list[list[dict[str, Any]]]]:
    """A configured engine that records the turns it was handed."""

    seen: list[list[dict[str, Any]]] = []

    async def converse(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen.append(turns)
        return [{"type": "text", "text": "Three of the eight remain inferred."}]

    unconfigured = DebriefEngines.unconfigured()
    return (
        DebriefEngines(
            name="claude-test",
            diarize=unconfigured.diarize,
            clean=unconfigured.clean,
            translate=unconfigured.translate,
            classify=unconfigured.classify,
            run_chain=unconfigured.run_chain,
            converse=converse,
        ),
        seen,
    )


def test_a_configured_debrief_answers_from_the_engine(
    recording_engines: tuple[DebriefEngines, list[list[dict[str, Any]]]],
) -> None:
    engines, seen = recording_engines
    client = TestClient(build_app(Backend(), debrief_engines=engines))
    meeting_id = _open_debrief(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/debrief/message", json={"message": QUESTION}
    )

    assert response.status_code == 200, response.text
    history = response.json()["history"]
    assert [turn["role"] for turn in history] == ["user", "assistant"]
    assert history[1]["content"] == [
        {"type": "text", "text": "Three of the eight remain inferred."}
    ]

    # The engine was handed the conversation, not just the latest line.
    assert seen, "the engine was never called"
    assert seen[-1][-1]["role"] == "user"
    assert QUESTION in str(seen[-1][-1]["content"])


def test_the_debrief_reply_is_never_the_request_echoed_back(
    recording_engines: tuple[DebriefEngines, list[list[dict[str, Any]]]],
) -> None:
    """The exact shape of the stub: an assistant turn derived from the question."""

    engines, _seen = recording_engines
    client = TestClient(build_app(Backend(), debrief_engines=engines))
    meeting_id = _open_debrief(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/debrief/message", json={"message": QUESTION}
    )

    assistant = response.json()["history"][1]
    rendered = " ".join(
        block.get("text", "") for block in assistant["content"] if isinstance(block, dict)
    )
    assert QUESTION not in rendered
    assert not rendered.startswith("ack")
