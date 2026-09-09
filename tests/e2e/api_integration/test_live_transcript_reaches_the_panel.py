"""Every speaker's words reach the panel, not only the ones that earn a nudge.

The panel could show four things: coverage, a nudge, the lane's health and the
room's languages. What it could not show was the conversation — so an operator
watching it had no way to tell a quiet meeting from a dead microphone, and no
way to check what a client actually said thirty seconds ago without leaving the
one screen they are meant to be on during a meeting.

Nothing had to be produced for this. `LiveUtterances` already recognises every
window server-side and already calls `observe(session_id, text, speaker)` —
finalised text *and* whoever the verifier believed said it. Both were read for
the trigger gate and then dropped. This keeps them and puts them on the stream
the panel is already connected to.

Driven through the production composition root, so what is asserted is the
assembly that ships.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _frames(client: TestClient, meeting_id: str) -> list[tuple[str, dict]]:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        lines = []
        for line in response.iter_lines():
            if line.startswith(":"):
                break
            lines.append(line)

    frames: list[tuple[str, dict]] = []
    name: str | None = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            frames.append((name, json.loads(line.removeprefix("data: "))))
            name = None
    return frames


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "logistics",
            "commercial_context": "Discovery",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _utterances(client: TestClient, meeting_id: str) -> list[dict]:
    return [payload for name, payload in _frames(client, meeting_id) if name == "utterance"]


def test_an_ordinary_sentence_reaches_the_panel_even_though_it_earns_no_nudge(
    client: TestClient,
) -> None:
    """The case that matters most, because it is most of a meeting.

    A sentence the gate declines is exactly the sentence the panel could never
    show before: `surfaced_nudges` is the only thing the stream carried, and
    most of a requirements meeting produces no nudge at all (FR-5.7). So the
    panel's silence meant both "nothing worth asking about" and "nothing heard
    at all", and an operator could not tell which.
    """

    meeting_id = _meeting(client)

    observed = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "We run three hundred and fifty consignments a day.", "speaker": "client"},
    )
    assert observed.status_code == 202, observed.text
    assert observed.json()["triggered"] is False

    (utterance,) = _utterances(client, meeting_id)
    assert utterance["text"] == "We run three hundred and fifty consignments a day."
    assert utterance["speaker"] == "client"


def test_the_transcript_keeps_the_order_it_was_said_in(client: TestClient) -> None:
    """A transcript out of order is worse than none: it misattributes an answer."""

    meeting_id = _meeting(client)
    said = [
        ("operator", "How many consignments do you move in a day?"),
        ("client", "Three hundred and fifty, give or take."),
        ("client", "More like four hundred in the run-up to Christmas."),
    ]
    for speaker, text in said:
        posted = client.post(
            f"/api/meetings/{meeting_id}/live/utterance",
            json={"text": text, "speaker": speaker},
        )
        assert posted.status_code == 202, posted.text

    assert [(u["speaker"], u["text"]) for u in _utterances(client, meeting_id)] == said


def test_a_speaker_nobody_could_identify_is_reported_as_unknown_rather_than_guessed(
    client: TestClient,
) -> None:
    """Nobody enrolled is the ordinary case, not an error state.

    `identify_speaker` answers `None` when no voiceprint is usable, which is
    almost every deployment. Reported as absence and rendered as absence: a
    line attributed to the wrong person is worse than a line attributed to
    nobody, and this transcript is read back mid-meeting to settle exactly
    that kind of question.
    """

    meeting_id = _meeting(client)
    posted = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "It depends which depot you mean."},
    )
    assert posted.status_code == 202, posted.text

    (utterance,) = _utterances(client, meeting_id)
    assert utterance["speaker"] is None


def test_a_panel_opened_mid_meeting_catches_up_on_what_it_missed(
    client: TestClient,
) -> None:
    """The reason the stream replays rather than tails.

    An operator opens the panel after the meeting has started, or the laptop
    lid closes and `EventSource` reconnects. Either way the transcript they
    get must be the meeting's, not the remainder of it.
    """

    meeting_id = _meeting(client)
    for text in ("Before the panel was open.", "And this one too."):
        client.post(f"/api/meetings/{meeting_id}/live/utterance", json={"text": text})

    first = [u["text"] for u in _utterances(client, meeting_id)]
    second = [u["text"] for u in _utterances(client, meeting_id)]

    assert first == ["Before the panel was open.", "And this one too."]
    # Read by index rather than drained, so a second panel does not take the
    # transcript away from the first — the same reading the nudges take.
    assert second == first


def test_a_nudge_and_the_line_that_caused_it_both_reach_the_panel(
    client: TestClient,
) -> None:
    """The transcript is an addition, not a replacement.

    An operator asked to trust a nudge needs the sentence that provoked it,
    and FR-5.11's trigger reason names the phrase without quoting the line.
    """

    meeting_id = _meeting(client)
    posted = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "The dashboard just has to be fast.", "speaker": "client"},
    )
    assert posted.status_code == 202, posted.text
    assert posted.json()["surfaced"] is True

    frames = _frames(client, meeting_id)
    assert [p["text"] for n, p in frames if n == "utterance"] == [
        "The dashboard just has to be fast."
    ]
    assert len([p for n, p in frames if n == "nudge"]) == 1


def test_every_line_carries_its_place_in_the_transcript(client: TestClient) -> None:
    """What a reconnecting panel dedupes on.

    A nudge survives a replay by its id. An utterance has none, and two people
    can say the same short sentence an hour apart, so nothing about the text
    separates a replayed line from a repeated one. The index does, and it is
    the server's to assign — a panel counting arrivals would number a replay
    from wherever it happened to be.
    """

    meeting_id = _meeting(client)
    for text in ("Yes.", "Sorry, could you repeat that?", "Yes."):
        client.post(f"/api/meetings/{meeting_id}/live/utterance", json={"text": text})

    heard = _utterances(client, meeting_id)
    assert [u["seq"] for u in heard] == [0, 1, 2]
    # The two identical lines are distinguishable, which is the whole point.
    assert heard[0]["text"] == heard[2]["text"]
    assert heard[0]["seq"] != heard[2]["seq"]


# --- how quickly a line reaches the panel --------------------------------
#
# The stream used to advance only on a quarter-second timer, so every line
# waited an average of 125ms for a loop that had nothing else to do. That is
# the cheapest kind of delay there is on the one path whose whole argument is
# arriving inside the conversational window — and it sat underneath a five
# second upload chunk, which is why nobody had noticed it.


def test_a_new_line_wakes_every_panel_watching_the_meeting(
    client: TestClient, backend
) -> None:
    """The accelerator, asserted directly rather than by timing.

    A test that measured how *fast* a line arrived would be a test about this
    machine's scheduler. What matters is that the signal is sent, after the
    line exists, to every connection watching.
    """

    import asyncio

    meeting_id = _meeting(client)
    watchers = {asyncio.Event(), asyncio.Event()}
    backend.live_watchers[meeting_id] = set(watchers)

    client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "We run three fifty a day.", "speaker": "client"},
    )

    assert all(watcher.is_set() for watcher in watchers)
    # And the line is already there when they wake: a stream signalled early
    # finds nothing, clears its event and sleeps, and then waits out the full
    # timeout for the line it was woken for — slower than not signalling.
    assert backend.live_transcript[meeting_id][-1]["text"] == "We run three fifty a day."


def test_another_meeting_is_not_woken(client: TestClient, backend) -> None:
    # One panel per meeting is the ordinary case, and waking all of them would
    # make every meeting's cost grow with every other meeting in the process.
    import asyncio

    mine = _meeting(client)
    theirs = _meeting(client)
    watcher = asyncio.Event()
    backend.live_watchers[theirs] = {watcher}

    client.post(
        f"/api/meetings/{mine}/live/utterance",
        json={"text": "Anything at all.", "speaker": "client"},
    )

    assert not watcher.is_set()


def test_a_panel_that_disconnects_leaves_nothing_behind(
    client: TestClient, backend
) -> None:
    """Left registered, every producer would go on setting an event for a
    panel that closed hours ago — for the life of the process, once per line,
    for every meeting anybody ever opened."""

    meeting_id = _meeting(client)
    _frames(client, meeting_id)
    _frames(client, meeting_id)

    assert backend.live_watchers.get(meeting_id) in (None, set())


def test_a_panel_closing_while_a_line_arrives_does_not_stop_the_transcript(
    client: TestClient, backend
) -> None:
    """The wake-up signal iterates the set of open panels, and the streams
    themselves add to and remove from it.

    Iterated directly, a panel closing at the moment a line is produced raises
    `Set changed size during iteration` — inside `observe_utterance`, inside
    the chunk handler, which swallows it. The visible symptom is a transcript
    that simply stops, with nothing anywhere saying why: exactly the failure
    the signal was added to make *faster*.
    """

    import asyncio

    meeting_id = _meeting(client)

    class _Closing(asyncio.Event):
        """A panel that disconnects the instant it is woken."""

        def set(self) -> None:  # type: ignore[override]
            backend.live_watchers[meeting_id].discard(self)
            super().set()

    backend.live_watchers[meeting_id] = {_Closing(), asyncio.Event(), _Closing()}

    observed = client.post(
        f"/api/meetings/{meeting_id}/live/utterance",
        json={"text": "Three fifty a day.", "speaker": "client"},
    )

    assert observed.status_code == 202, observed.text
    assert backend.live_transcript[meeting_id][-1]["text"] == "Three fifty a day."


# --- a sentence, as it is being said -------------------------------------
#
# Waiting for a finished turn means nothing appears until the recogniser is
# sure the speaker has stopped — about a second after they do, and longer if
# they trail off. The screen sat blank through every sentence and then printed
# it whole. Interim lines are what let it keep up with the room.
#
# Driven through the lane's own entry point rather than a route: interim lines
# never travel over HTTP, they are handed straight from the socket reader, so
# a test written against a route would be testing a fiction.


def test_one_sentence_is_one_line_that_grows(client: TestClient, backend) -> None:
    """Rewritten in place, not appended to.

    Appended, a five-word sentence would arrive as five lines, each a longer
    copy of the last, and an hour of meeting would be unreadable.
    """

    import asyncio

    meeting_id = _meeting(client)
    observe = client.app.state.observe_live_text

    async def spoken() -> None:
        await observe(meeting_id, "So how are", None, turn=0, final=False)
        await observe(meeting_id, "So how are arrivals", None, turn=0, final=False)
        await observe(meeting_id, "So how are arrivals booked?", None, turn=0, final=True)

    asyncio.run(spoken())

    held = backend.live_transcript[meeting_id]
    assert [line["text"] for line in held] == ["So how are arrivals booked?"]
    assert held[-1].get("final", True) is True


def test_the_next_sentence_is_a_new_line(client: TestClient, backend) -> None:
    """Keyed on the vendor's turn index, because "the last line" is not
    enough: a finished turn and the first update of the next arrive in quick
    succession, and only the index says which is which."""

    import asyncio

    meeting_id = _meeting(client)
    observe = client.app.state.observe_live_text

    async def spoken() -> None:
        await observe(meeting_id, "First one.", None, turn=0, final=True)
        await observe(meeting_id, "And the", None, turn=1, final=False)
        await observe(meeting_id, "And the second.", None, turn=1, final=True)

    asyncio.run(spoken())

    assert [line["text"] for line in backend.live_transcript[meeting_id]] == [
        "First one.",
        "And the second.",
    ]


def test_an_unfinished_line_never_reaches_the_gate(client: TestClient, backend) -> None:
    """A question raised from half a sentence is worse than one raised a
    moment later, and interim text is by definition text that may change."""

    import asyncio

    meeting_id = _meeting(client)
    observe = client.app.state.observe_live_text

    asyncio.run(observe(meeting_id, "We only get a few", None, turn=0, final=False))

    assert backend.live_transcript[meeting_id][-1]["final"] is False
    assert backend.surfaced_nudges.get(meeting_id, []) == []


def test_a_growing_line_reaches_the_panel_on_the_same_seq(
    client: TestClient, backend
) -> None:
    """The panel files a line at its index, so a line that grows must keep
    its index — arriving under a new one, the same sentence would stack up as
    several things somebody said."""

    import asyncio

    meeting_id = _meeting(client)
    observe = client.app.state.observe_live_text
    asyncio.run(observe(meeting_id, "So how are", None, turn=0, final=False))

    growing = _utterances(client, meeting_id)
    assert [(u["seq"], u["text"], u["final"]) for u in growing] == [(0, "So how are", False)]

    asyncio.run(observe(meeting_id, "So how are arrivals booked?", None, turn=0, final=True))

    settled = _utterances(client, meeting_id)
    assert [(u["seq"], u["text"], u["final"]) for u in settled] == [
        (0, "So how are arrivals booked?", True)
    ]
