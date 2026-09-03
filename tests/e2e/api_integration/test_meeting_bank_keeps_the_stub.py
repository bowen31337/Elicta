"""The panel's glanceable tier reaches the panel.

`NudgeStack` renders a nudge in two tiers — a short `stub` above the full
question, heavier than it — because an operator mid-meeting is looking at a
client rather than at this. The Analyst prompt asks for one: "the same
question at a glance, short enough to read without breaking eye contact."

It arrived empty every time, and had since the field existed. Neither
`BankCandidate` declared `stub`, and pydantic ignores an undeclared keyword
rather than refusing it, so `_store_compiled_candidates` passed the value and
it vanished without an error. Measured on a real state file: 554 candidates,
554 empty stubs, against phrasings averaging 112 characters and reaching 240.
The top tier had never had anything in it.

Two drops, one behind the other, which is why this is asserted through the
route rather than on the model. The engagement's candidate lost its stub on
the way into storage; the meeting's bank lost it again in
`get_base_candidates`, which rebuilds each candidate field by field. Fixing
either alone leaves the panel exactly as empty.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.composition import Backend
from app.modules.compiler.api.models import BankCandidate as ApiBankCandidate
from app.modules.compiler.api.recompile import (
    InheritedOpenQuestion as ApiInheritedOpenQuestion,
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


def test_a_meeting_bank_carries_the_short_form_the_panel_reads(
    client: TestClient, backend: Backend
) -> None:
    engagement_id = _engagement(client)
    meeting_id = _meeting(client, engagement_id)

    backend.compiled_candidates[engagement_id] = [
        ApiBankCandidate(
            id="c-1",
            template_section="Volumes",
            phrasing=(
                "How many arrivals do you handle in a month, across all three "
                "sites, and how much does that move between peak and trough?"
            ),
            priority=1,
            stub="Monthly arrivals",
            trigger_types=["unquantified_amount"],
        ),
    ]

    bank = client.get(f"/api/meetings/{meeting_id}/bank")
    assert bank.status_code == 200, bank.text
    (candidate,) = bank.json()["candidates"]

    assert candidate["stub"] == "Monthly arrivals"
    # The long form is still there. The short one is an additional tier, not a
    # replacement: the operator glances at the stub and reads the phrasing
    # aloud, so losing either leaves them with half a question.
    assert candidate["phrasing"].startswith("How many arrivals")


def test_a_carried_forward_question_reports_no_stub_rather_than_a_borrowed_one(
    client: TestClient, backend: Backend
) -> None:
    """An inherited open question is prose from the last meeting, not a drafted
    candidate, so nothing about it was ever shortened.

    Reported as empty rather than defaulted to the phrasing. Substituting the
    long form here would make a question that has a real short form
    indistinguishable from one that does not, and the caller derives a short
    form of its own precisely by being able to tell.
    """

    engagement_id = _engagement(client)
    meeting_id = _meeting(client, engagement_id)
    backend.engagement_open_questions[engagement_id] = [
        ApiInheritedOpenQuestion(
            text="What happens to a booking when a vessel is late?", impact_rank=1
        )
    ]

    bank = client.get(f"/api/meetings/{meeting_id}/bank")
    assert bank.status_code == 200, bank.text
    (inherited,) = bank.json()["candidates"]

    assert inherited["inherited_from_open_question"] is True
    assert inherited["stub"] == ""
