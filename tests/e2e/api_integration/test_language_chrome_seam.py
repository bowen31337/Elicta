"""The panel's language strip has to be fed by something.

Journey 4 says the panel "shows which languages it is hearing, and how well it
supports them", and calls that ready. A live run photographed it reading **No
language detected** — permanently, for a reason no screenshot can show: the
session stream carries three kinds of frame (`lane`, `coverage`, `nudge`) and
none of them is a language, so the panel's language list is initialised empty
and nothing ever adds to it.

Meanwhile the service already works out which languages to expect in the room.
`derive_and_persist_expected_languages` runs when an engagement is created and
writes them to the engagement row — and nothing has ever read them back. That is
journey 1's promise ("what lets Elicta work out which languages to expect")
sitting one field away from journey 4's empty strip.

These join the two. What the stream now carries is *expected*, not heard —
saying a language was detected when nothing transcribed would be the same false
claim in a new place.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _engagement(client: TestClient, organisation: str, sector: str, context: str) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": organisation,
            "sector": sector,
            "commercial_context": context,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def _meeting(client: TestClient, engagement_id: str) -> str:
    created = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "line-in"},
    )
    assert created.status_code == 201, created.text
    return created.json()["meeting_id"]


def _frames(client: TestClient, meeting_id: str) -> list[tuple[str, dict]]:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        body = "".join(response.iter_text())

    frames: list[tuple[str, dict]] = []
    name: str | None = None
    for line in body.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            frames.append((name, json.loads(line.removeprefix("data: "))))
            name = None
    return frames


def test_the_stream_carries_the_languages_the_room_is_expected_to_use(
    client: TestClient,
) -> None:
    engagement_id = _engagement(
        client, "Northwind Logistics", "Freight", "Discovery with the Shenzhen depot team"
    )
    meeting_id = _meeting(client, engagement_id)

    languages = [payload for name, payload in _frames(client, meeting_id) if name == "language"]

    assert [entry["language"] for entry in languages] == ["en", "zh"]


def test_an_expected_language_does_not_claim_to_have_been_heard(client: TestClient) -> None:
    """The distinction the whole strip rests on.

    Nothing transcribes yet, so a frame that said "detected" would put a claim
    on screen that no audio supports — which is exactly the failure this seam
    is being closed to stop repeating.
    """

    engagement_id = _engagement(client, "Northwind", "Freight", "Shenzhen depot")
    meeting_id = _meeting(client, engagement_id)

    languages = [payload for name, payload in _frames(client, meeting_id) if name == "language"]

    assert languages, "no language frames at all"
    assert all(entry["expected"] is True for entry in languages)
    assert all("confidence" not in entry for entry in languages), (
        "an expected language has no observation behind it, so it has no confidence"
    )


def test_lane_still_leads_the_stream(client: TestClient) -> None:
    """The panel has to know which mode it is in before it renders anything."""

    engagement_id = _engagement(client, "Northwind", "Freight", "Shenzhen depot")
    meeting_id = _meeting(client, engagement_id)

    assert _frames(client, meeting_id)[0][0] == "lane"


def test_an_english_only_engagement_says_english_rather_than_nothing(
    client: TestClient,
) -> None:
    engagement_id = _engagement(client, "Calder & Rowe", "Legal", "Matter management")
    meeting_id = _meeting(client, engagement_id)

    languages = [payload for name, payload in _frames(client, meeting_id) if name == "language"]

    assert [entry["language"] for entry in languages] == ["en"]


def test_a_meeting_with_no_engagement_behind_it_claims_no_languages(
    client: TestClient,
) -> None:
    """Better an empty strip than a confident wrong one."""

    frames = _frames(client, "meeting-nobody-created")

    assert [name for name, _ in frames if name == "language"] == []


def test_an_engagement_created_before_this_existed_still_lights_the_strip(
    client: TestClient, backend
) -> None:
    """The derivation runs once, at creation, and never again.

    So an engagement made before the languages were persisted has an empty
    column and no path back — its panel would stay blank for ever while every
    new client's worked. The derivation is pure and cheap, so an engagement
    with nothing stored is derived from its own client context on read.
    """

    engagement_id = _engagement(
        client, "Northwind Logistics", "Freight", "Discovery with the Shenzhen depot team"
    )
    meeting_id = _meeting(client, engagement_id)

    # Exactly the state an older engagement is in: the row exists, the derived
    # languages do not.
    backend.expected_languages.pop(engagement_id, None)

    languages = [payload for name, payload in _frames(client, meeting_id) if name == "language"]

    assert [entry["language"] for entry in languages] == ["en", "zh"]
