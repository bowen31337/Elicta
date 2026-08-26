"""The coverage meter counts what is in the database, not what a browser remembers.

Three defects met here, and they were one chain.

`_coverage_slots_for_meeting` reported `filled: False` for every section,
always -- nothing in the service ever computed it. So the only thing that
moved the meter was a `localStorage` record of the operator's own taps, which
no other device could see and no restart could be trusted with.

Worse, the tap was attributed to whichever section happened to be first
unticked, not to the section the nudge was about. Eight questions about "a
lot" and "some" ticked off Volumes, Performance and Integrations in list
order, and the panel reported eight of eight covered on evidence of nothing.

And the mark was one-way: with every section ticked the `Asked it` chip was
gated out of existence, so no further disposition could ever be recorded.

The fix is to derive the meter from what is already durable. A section counts
as asked about when a nudge belonging to it was marked `taken`. That needs no
new table, survives a restart because `surfaced_nudges` does, and is the same
answer on every screen reading the meeting.

Driven through the production composition root, so what is asserted ships.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time

from fastapi.testclient import TestClient

from app.composition import Backend, build_app


@contextlib.contextmanager
def _client(url: str):
    """The production assembly over a real database, plus its backend.

    The backend comes out too so a test can seed a compiled bank. Compiling
    one for real needs a model, and what is under test here is the
    attribution, not the compiler.
    """

    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend)) as client:
        yield client, backend
    store.close()


def _engagement_of(client: TestClient, meeting_id: str) -> str:
    listing = client.get("/api/engagements").json()["items"]
    return listing[0]["engagement_id"]


def _seed_bank(backend: Backend, engagement_id: str, section: str) -> None:
    """One candidate, in one section, for a nudge to be drawn from."""

    from app.modules.compiler.api.models import BankCandidate

    # Reassigned whole rather than appended to: a `DurableMapping` persists
    # through `__setitem__` alone, so `.setdefault(k, []).append(v)` writes to
    # memory and nowhere else.
    backend.compiled_candidates[engagement_id] = [
        BankCandidate(
            id=f"{engagement_id}-candidate-1",
            template_section=section,
            # Carries the term the utterance uses, which is the first tier
            # of `select`'s relevance check — a candidate matched on neither
            # the term nor the trigger type is not about this hit, and falls
            # through to a template question naming no section.
            phrasing="You said a lot of joiners — how many is that?",
            priority=1,
            trigger_types=["unquantified_amount"],
        )
    ]


def _meeting(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Coverage",
            "sector": "s",
            "commercial_context": "c",
        },
    )
    assert engagement.status_code == 201, engagement.text
    meeting = client.post(
        "/api/meetings",
        json={
            "engagement_id": engagement.json()["engagement_id"],
            "capture_mode": "microphone",
        },
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _frames(client: TestClient, meeting_id: str, name: str) -> list[dict]:
    """Every frame of one kind currently on the stream."""

    stream = client.get(f"/api/meetings/{meeting_id}/session/stream")
    out, wanted = [], f"event: {name}"
    lines = stream.text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == wanted and index + 1 < len(lines):
            body = lines[index + 1]
            if body.startswith("data: "):
                out.append(json.loads(body[6:]))
    return out


def _say(client: TestClient, meeting_id: str, text: str) -> dict:
    said = client.post(f"/api/meetings/{meeting_id}/live/utterance", json={"text": text})
    assert said.status_code == 202, said.text
    return said.json()


def test_a_nudge_says_which_section_it_is_about(tmp_path):
    """Otherwise the panel has nothing to attribute a tap to."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        _say(client, meeting_id, "We onboard a lot of joiners each intake.")

        nudges = _frames(client, meeting_id, "nudge")
        assert nudges, "the utterance was supposed to surface a nudge"
        assert "template_section" in nudges[0]


def test_a_nudge_drawn_from_no_candidate_names_no_section(tmp_path):
    """A template fallback belongs to nothing, and must not be given a section."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        # No bank was compiled here, so nothing can be drawn from a candidate.
        _say(client, meeting_id, "We onboard a lot of joiners each intake.")

        nudges = _frames(client, meeting_id, "nudge")
        assert nudges
        assert nudges[0]["template_section"] is None


def test_coverage_starts_empty_and_no_tap_of_the_operators_can_forge_it(tmp_path):
    """The starting state is honest, and stays honest until something is answered."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        _say(client, meeting_id, "We onboard a lot of joiners each intake.")

        coverage = _frames(client, meeting_id, "coverage")[0]
        assert coverage["slots"], "a meeting has sections to cover"
        assert all(not slot["filled"] for slot in coverage["slots"])


def test_marking_a_nudge_asked_fills_that_nudges_own_section(tmp_path):
    """Its own -- not whichever section happened to be first in the list.

    Needs a bank: the attribution runs candidate -> section, and with nothing
    compiled every nudge is a template fallback naming no section, so the
    assertion would hold against a meter that still moved by position.
    """

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        engagement_id = _engagement_of(client, meeting_id)
        # Deliberately not first in the section list: a meter that fills by
        # position would fill the first section and pass a weaker check.
        _seed_bank(backend, engagement_id, section="Volumes")

        _say(client, meeting_id, "We onboard a lot of joiners each intake.")
        nudge = _frames(client, meeting_id, "nudge")[0]
        assert nudge["template_section"] == "Volumes", (
            "the nudge was drawn from the seeded candidate"
        )

        recorded = client.post(
            f"/api/meetings/{meeting_id}/nudges/{nudge['id']}/disposition",
            json={"disposition": "taken"},
        )
        assert recorded.status_code == 200, recorded.text

        slots = _frames(client, meeting_id, "coverage")[0]["slots"]
        filled = {slot["id"] for slot in slots if slot["filled"]}
        assert filled == {"Volumes"}, (
            "a tap fills the section its nudge belongs to, and no other"
        )


def test_a_parked_nudge_fills_nothing(tmp_path):
    """Parking defers the thread. Nothing about it was asked."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        _say(client, meeting_id, "We onboard a lot of joiners each intake.")
        nudge = _frames(client, meeting_id, "nudge")[0]

        client.post(
            f"/api/meetings/{meeting_id}/nudges/{nudge['id']}/disposition",
            json={"disposition": "parked"},
        )

        slots = _frames(client, meeting_id, "coverage")[0]["slots"]
        assert all(not slot["filled"] for slot in slots)


def test_what_the_operator_marked_is_still_there_after_a_restart(tmp_path):
    """The point of moving it out of the browser."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        _say(client, meeting_id, "We onboard a lot of joiners each intake.")
        nudge = _frames(client, meeting_id, "nudge")[0]
        client.post(
            f"/api/meetings/{meeting_id}/nudges/{nudge['id']}/disposition",
            json={"disposition": "taken"},
        )
        before = [s for s in _frames(client, meeting_id, "coverage")[0]["slots"] if s["filled"]]

    with _client(url) as (client, backend):
        after = [s for s in _frames(client, meeting_id, "coverage")[0]["slots"] if s["filled"]]

    assert after == before


def test_the_meter_moves_on_the_connection_the_panel_already_has(tmp_path, monkeypatch):
    """Otherwise the operator sees the old count until something reconnects.

    Coverage was a single frame sent at stream open, which was adequate while
    nothing server-side ever changed it -- the panel kept its own count and
    the frame was only a starting point. Now that the count is derived here,
    a meter that only refreshes on reconnect is wrong for minutes at a time,
    mid-meeting, which is the one place it is read.
    """

    # Read when the app is assembled, not per request, so it goes before the
    # build. The suite's 20ms default would close this stream before the
    # round trip it is waiting on could happen. Nothing here sits out the
    # window: the read below stops at the second frame.
    monkeypatch.setenv("ELICTA_SESSION_STREAM_HOLD_SECONDS", "10")

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url) as (client, backend):
        meeting_id = _meeting(client)
        _seed_bank(backend, _engagement_of(client, meeting_id), section="Volumes")
        nudge_id = _say(client, meeting_id, "We onboard a lot of joiners each intake.")[
            "nudge_id"
        ]

        # Recorded from another thread. Reading a held stream occupies the
        # calling thread completely -- a POST issued between two reads of the
        # same response does not run until the stream finishes, so the frame
        # it should have caused would arrive after the connection it was
        # meant to travel on had closed.
        def record_shortly() -> None:
            time.sleep(0.5)
            client.post(
                f"/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition",
                json={"disposition": "taken"},
            )

        recorder = threading.Thread(target=record_shortly, daemon=True)
        recorder.start()

        with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as held:
            seen: list[dict] = []
            for line in held.iter_lines():
                if line.startswith("data: ") and '"slots"' in line:
                    seen.append(json.loads(line[6:]))
                    if len(seen) == 2:
                        break
        recorder.join(timeout=5)

    assert len(seen) == 2, "the held connection never carried a second coverage frame"
    assert not any(slot["filled"] for slot in seen[0]["slots"])
    assert [slot["id"] for slot in seen[1]["slots"] if slot["filled"]] == ["Volumes"]
