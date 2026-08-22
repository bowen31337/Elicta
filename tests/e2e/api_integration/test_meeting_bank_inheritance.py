"""A meeting's bank is the engagement's work, weighted by what is still open.

`recompile_meeting_bank` has been built and unit-tested throughout: it takes
base candidates and inherited open questions and returns a ranked bank with the
carried-forward questions ahead of everything else. Both of its inputs were read
off `Backend` fields that nothing in the composition root ever wrote, so the
route served `{"candidates": []}` for every meeting of every engagement, and a
live run failed on "the second meeting inherits candidate questions" with an
empty bank and a fresh timestamp.

Both inputs already exist one level up, on the engagement. Nothing had to be
produced — only joined.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.composition import Backend
from app.modules.compiler.api.models import BankCandidate as ApiBankCandidate
from app.modules.compiler.api.recompile import (
    InheritedOpenQuestion as ApiInheritedOpenQuestion,
)


def _candidate(identifier: str, phrasing: str, priority: int, *, pruned: bool = False):
    return ApiBankCandidate(
        id=identifier,
        template_section="volumes",
        phrasing=phrasing,
        priority=priority,
        pruned=pruned,
    )


def _engagement(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind",
            "sector": "Freight",
            "commercial_context": "Depot discovery",
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


def test_a_meeting_bank_is_built_from_its_engagement_s_compiled_candidates(
    client: TestClient, backend: Backend
) -> None:
    engagement_id = _engagement(client)
    backend.compiled_candidates[engagement_id] = [
        _candidate("c1", "How many orders a month?", 1),
        _candidate("c2", "Which depots are in scope?", 2),
    ]

    meeting_id = _meeting(client, engagement_id)
    bank = client.get(f"/api/meetings/{meeting_id}/bank").json()

    assert [candidate["phrasing"] for candidate in bank["candidates"]] == [
        "How many orders a month?",
        "Which depots are in scope?",
    ]


def test_an_open_question_carried_from_last_time_outranks_every_fresh_candidate(
    client: TestClient, backend: Backend
) -> None:
    """The whole point of recompiling per meeting.

    You do not re-ask what was settled, and what was left hanging is the first
    thing worth raising — so an inherited question is this meeting's highest
    priority, not merely present somewhere in the list.
    """

    engagement_id = _engagement(client)
    backend.compiled_candidates[engagement_id] = [_candidate("c1", "A fresh one", 1)]
    backend.engagement_open_questions[engagement_id] = [
        ApiInheritedOpenQuestion(text="What did they mean by Q3?", impact_rank=1)
    ]

    meeting_id = _meeting(client, engagement_id)
    bank = client.get(f"/api/meetings/{meeting_id}/bank").json()

    first = bank["candidates"][0]
    assert first["phrasing"] == "What did they mean by Q3?"
    assert first["inherited_from_open_question"] is True
    assert [c["phrasing"] for c in bank["candidates"]] == [
        "What did they mean by Q3?",
        "A fresh one",
    ]


def test_a_pruned_candidate_stays_pruned_in_every_meeting_bank(
    client: TestClient, backend: Backend
) -> None:
    """Pruning is the operator's judgement, and it is why they reviewed the bank.

    Journey 1 promises a pruned question "does not come back the next time the
    bank is drafted". A per-meeting recompile that reinstated it would break
    that promise once per meeting, which is worse than never having offered
    pruning at all.
    """

    engagement_id = _engagement(client)
    backend.compiled_candidates[engagement_id] = [
        _candidate("c1", "Kept", 1),
        _candidate("c2", "Pruned by the operator", 2, pruned=True),
    ]

    meeting_id = _meeting(client, engagement_id)
    bank = client.get(f"/api/meetings/{meeting_id}/bank").json()

    assert [c["phrasing"] for c in bank["candidates"]] == ["Kept"]


def test_a_meeting_whose_engagement_compiled_nothing_has_an_empty_bank(
    client: TestClient
) -> None:
    """Empty because there is nothing, not empty because nothing was joined."""

    meeting_id = _meeting(client, _engagement(client))

    assert client.get(f"/api/meetings/{meeting_id}/bank").json()["candidates"] == []
