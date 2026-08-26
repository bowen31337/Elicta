"""A meeting's nudges outlive the process that raised them.

Held in memory, a restart lost the lot. Two things went with them, and the
second is the one nobody would have predicted: the panel's history — the
operator's only route back to a question they had not dealt with — and
`raised_nudges`, which is what resolves a thread id. `Park it` and `Go
deeper` send an id and nothing else, so after a restart every nudge raised
before it answered 404, from a panel still showing it.

Driven through the production composition root, so what is asserted is the
assembly that ships.
"""

from __future__ import annotations

import contextlib
import json

from fastapi.testclient import TestClient

from app.composition import Backend, build_app


@contextlib.contextmanager
def _client(url: str):
    """The production assembly, over a real database on disk.

    Entered as a context manager rather than constructed bare: an unentered
    `TestClient` has no portal, and a streaming read against one blocks for
    ever rather than failing.
    """

    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    with TestClient(build_app(attach_state_store(Backend(), store))) as client:
        yield client
    store.close()


def _meeting(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "logistics",
            "commercial_context": "Discovery",
        },
    ).json()["engagement_id"]
    return client.post(
        "/api/meetings",
        json={"engagement_id": engagement, "capture_mode": "live"},
    ).json()["meeting_id"]


def _nudges_on_stream(client: TestClient, meeting_id: str) -> list[dict]:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        lines = []
        for line in response.iter_lines():
            if line.startswith(":"):
                break
            lines.append(line)
    out: list[dict] = []
    name = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name == "nudge":
            out.append(json.loads(line.removeprefix("data: ")))
            name = None
    return out


def test_a_nudge_is_still_on_the_stream_after_a_restart(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as first:
        meeting_id = _meeting(first)
        first.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "The dashboard just has to be fast.", "speaker": "client"},
        )
        assert _nudges_on_stream(first, meeting_id), "nothing was raised to begin with"

    # The process goes away and comes back against the same database.
    with _client(url) as restarted:
        assert _nudges_on_stream(restarted, meeting_id), "the meeting's history was lost"


def test_a_thread_can_still_be_parked_after_a_restart(tmp_path) -> None:
    """The failure the panel would hit first, and the quietest one.

    `Park it` sends an id and nothing else. Without the meeting behind it the
    service cannot say which engagement to file the question against, so it
    answered 404 to a panel that was still showing the nudge.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as first:
        meeting_id = _meeting(first)
        first.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "The dashboard just has to be fast.", "speaker": "client"},
        )
        nudge_id = _nudges_on_stream(first, meeting_id)[0]["id"]

    with _client(url) as restarted:
        parked = restarted.post(f"/api/threads/{nudge_id}/park")

    assert parked.status_code == 200, parked.text


def test_the_next_nudge_does_not_reuse_an_id_it_has_already_issued(tmp_path) -> None:
    """The same trap the document and vocabulary ids were fixed for.

    Counting from zero after a restart hands the next nudge an id a stored
    one already has — and `Park it` addresses a thread by id, so the operator
    would file one question believing they had filed another.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as first:
        meeting_id = _meeting(first)
        first.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "The dashboard just has to be fast.", "speaker": "client"},
        )
        before = {n["id"] for n in _nudges_on_stream(first, meeting_id)}

    with _client(url) as restarted:
        restarted.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "We move many pallets a day.", "speaker": "client"},
        )
        after = [n["id"] for n in _nudges_on_stream(restarted, meeting_id)]

    assert len(after) == len(set(after)), f"an id was reissued: {after}"
    assert set(after) > before, "the earlier nudge was replaced rather than kept"


def test_a_nudge_that_was_dealt_with_says_so_on_the_stream(tmp_path) -> None:
    """So the panel can mark it, and the operator does not act on it twice.

    The disposition was appended to its own list and never reached the nudge
    it was about, so a history entry for a question already asked looked
    exactly like one still waiting. Two records of one fact, and the one the
    panel reads was not the one being written.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as first:
        meeting_id = _meeting(first)
        first.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "The dashboard just has to be fast.", "speaker": "client"},
        )
        nudge_id = _nudges_on_stream(first, meeting_id)[0]["id"]

        first.post(
            f"/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition",
            json={"disposition": "taken"},
        )

        surfaced = _nudges_on_stream(first, meeting_id)[0]
        assert surfaced["disposition"] == "taken"

    # And it is still marked after a restart, which is when the operator is
    # least able to remember what they already asked.
    with _client(url) as restarted:
        assert _nudges_on_stream(restarted, meeting_id)[0]["disposition"] == "taken"


def test_a_nudge_nobody_has_answered_carries_no_disposition(tmp_path) -> None:
    """Unanswered is a state, not a default — a nudge nobody got to is not
    one that was ignored."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as first:
        meeting_id = _meeting(first)
        first.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": "The dashboard just has to be fast.", "speaker": "client"},
        )

        assert _nudges_on_stream(first, meeting_id)[0]["disposition"] is None
