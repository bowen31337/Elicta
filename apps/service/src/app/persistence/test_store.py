"""Durability tests: state has to be there after the process that wrote it is gone.

Each test writes through the real HTTP API, throws the application away, builds
a second one against the same database file, and reads back over HTTP. Nothing
is carried between the two apps in Python — the only channel is the file — so a
pass means the data genuinely round-tripped through storage rather than through
a shared object a test fixture kept alive.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, attach_state_store, build_app
from app.persistence import open_state_store
from app.persistence.store import DurableMapping


@pytest.fixture
def database(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'state.db'}"


def client_for(database: str) -> TestClient:
    """A fresh application bound to an existing database file.

    Deliberately builds a brand-new `Backend`, so anything a previous client
    wrote can only reappear by being read back off disk.
    """

    return TestClient(build_app(attach_state_store(Backend(), open_state_store(database))))


def test_an_engagement_survives_a_restart(database: str) -> None:
    with client_for(database) as first:
        created = first.post(
            "/api/engagements",
            json={
                "client_organisation": "Northwind Logistics",
                "sector": "Freight and warehousing",
                "commercial_context": "Fleet visibility programme",
            },
        )
        assert created.status_code == 201, created.text
        engagement_id = created.json()["engagement_id"]

    with client_for(database) as second:
        # The engagement is known to an application that never saw the POST.
        patched = second.patch(
            f"/api/engagements/{engagement_id}",
            json={"purpose": "Discovery"},
        )
        assert patched.status_code == 200, patched.text


def test_an_unknown_engagement_is_still_unknown_after_a_restart(database: str) -> None:
    # The mirror of the test above: durability that answered 200 for
    # everything would pass that one while being useless.
    with client_for(database) as client:
        assert client.patch("/api/engagements/eng-404", json={"purpose": "x"}).status_code == 404


def test_carried_forward_state_survives_a_restart(database: str) -> None:
    """The FR-8.9 / FR-4.8 premise: what an engagement remembers outlives it."""

    from datetime import UTC, datetime

    from app.modules.compiler.api.recompile import InheritedOpenQuestion
    from app.modules.debrief.artifacts.models import RequirementsState

    store = open_state_store(database)
    questions = store.open_questions(lambda row: InheritedOpenQuestion(**row))
    questions["eng-1"] = [
        InheritedOpenQuestion(text="What does “fast” mean in seconds?", impact_rank=1),
        InheritedOpenQuestion(text="Which integrations are in scope?", impact_rank=2),
    ]
    state = store.requirements_state(lambda row: RequirementsState(**row))
    state["eng-1"] = RequirementsState(
        engagement_id="eng-1",
        confirmed_requirements=[],
        contradictions=[],
        decisions=[],
        updated_at=datetime.now(UTC),
    )
    store.close()

    reopened = open_state_store(database)
    reloaded = reopened.open_questions(lambda row: InheritedOpenQuestion(**row))
    # Ranked ascending on the way back out, not merely present.
    assert [q.impact_rank for q in reloaded["eng-1"]] == [1, 2]
    assert reloaded["eng-1"][0].text.startswith("What does")
    assert reopened.requirements_state(lambda row: RequirementsState(**row))["eng-1"]


def test_the_candidate_bank_keeps_its_compiled_order(database: str) -> None:
    from app.modules.compiler.api.models import BankCandidate

    store = open_state_store(database)
    bank = store.candidates(lambda row: BankCandidate(**row))
    # Priority and position disagree on purpose: the bank is stored in the
    # order it was compiled in, and a store that sorted by priority on the way
    # back would look correct on any list where the two happen to agree.
    bank["eng-1"] = [
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=3),
        BankCandidate(id="c-2", template_section="Integrations", phrasing="Which systems?", priority=1),
    ]
    store.close()

    reloaded = open_state_store(database).candidates(lambda row: BankCandidate(**row))
    assert [c.id for c in reloaded["eng-1"]] == ["c-1", "c-2"]


def test_replacing_a_list_does_not_leave_the_old_entries_behind(database: str) -> None:
    from app.modules.compiler.api.recompile import InheritedOpenQuestion

    store = open_state_store(database)
    questions = store.open_questions(lambda row: InheritedOpenQuestion(**row))
    questions["eng-1"] = [InheritedOpenQuestion(text="Old", impact_rank=1)]
    questions["eng-1"] = [InheritedOpenQuestion(text="New", impact_rank=1)]
    store.close()

    reloaded = open_state_store(database).open_questions(lambda row: InheritedOpenQuestion(**row))
    assert [q.text for q in reloaded["eng-1"]] == ["New"]


def test_deleting_removes_the_row(database: str) -> None:
    from app.modules.engagement.api.schemas import EngagementCreateRequest

    store = open_state_store(database)
    decode = lambda row: EngagementCreateRequest(**row)  # noqa: E731
    engagements = store.engagements(decode)
    engagements["eng-1"] = EngagementCreateRequest(
        client_organisation="Northwind", sector="Freight", commercial_context="Fleet"
    )
    del engagements["eng-1"]
    store.close()

    assert "eng-1" not in open_state_store(database).engagements(decode)


def test_a_durable_mapping_is_still_a_mapping(database: str) -> None:
    """The substitution only works because routers cannot tell the difference."""

    from app.modules.engagement.api.schemas import EngagementCreateRequest

    decode = lambda row: EngagementCreateRequest(**row)  # noqa: E731
    engagements = open_state_store(database).engagements(decode)
    assert isinstance(engagements, DurableMapping)

    payload = EngagementCreateRequest(
        client_organisation="Northwind", sector="Freight", commercial_context="Fleet"
    )
    engagements["eng-1"] = payload
    assert engagements.get("eng-1") == payload
    assert engagements.get("eng-2") is None
    assert "eng-1" in engagements
    assert len(engagements) == 1
    assert list(engagements) == ["eng-1"]
    assert [value.sector for value in engagements.values()] == ["Freight"]


def test_only_the_continuity_fields_are_made_durable() -> None:
    """Per-run pipeline scratch stays in memory, and that is deliberate."""

    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.engagements, DurableMapping)
    assert isinstance(backend.requirements_states, DurableMapping)
    assert isinstance(backend.engagement_open_questions, DurableMapping)
    assert isinstance(backend.compiled_candidates, DurableMapping)
    assert isinstance(backend.meeting_details, DurableMapping)

    # Rebuilt from the transcript on demand; storing it would mean maintaining
    # a second copy of something derived.
    assert isinstance(backend.transcript_cleanings, dict)
    assert not isinstance(backend.transcript_cleanings, DurableMapping)


def _engagement(client: TestClient, organisation: str) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": organisation,
            "sector": "Freight and warehousing",
            "commercial_context": "Fleet visibility programme",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def test_a_meeting_created_after_a_restart_does_not_overwrite_an_earlier_one(
    database: str,
) -> None:
    """The meeting id counter has to be derived from the rows, not the process.

    `meeting_details` is durable and `next_meeting_id` was not, so a restarted
    service minted `meeting-1` again and it landed on top of whichever real
    meeting already held that id — the exact collision
    `highest_engagement_ordinal`'s docstring describes for engagements, with no
    equivalent guard for meetings.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        created = first.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "live"},
        )
        assert created.status_code == 201, created.text
        original = created.json()["meeting_id"]

    with client_for(database) as second:
        second_meeting = second.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "record"},
        )
        assert second_meeting.status_code == 201, second_meeting.text
        assert second_meeting.json()["meeting_id"] != original

        # And the first one is still itself, not the second wearing its id.
        response = second.get(f"/api/meetings/{original}")
        assert response.status_code == 200, response.text
        assert response.json()["capture_mode"] == "live"

        listed = second.get(f"/api/engagements/{engagement_id}/meetings")
        assert listed.status_code == 200, listed.text
        assert [row["meeting_id"] for row in listed.json()["meetings"]] == [
            original,
            second_meeting.json()["meeting_id"],
        ]


def test_the_engagement_list_keeps_creation_order_across_a_restart(database: str) -> None:
    """A restart must not reorder the list an operator navigates by.

    `engagement_ids` only holds what the running process minted, so ordering
    on it put the engagement created a minute ago ahead of every engagement
    that came before it.
    """

    with client_for(database) as first:
        older = _engagement(first, "Northwind Logistics")

    with client_for(database) as second:
        newer = _engagement(second, "Harbourline Ferries")

        response = second.get("/api/engagements")

        assert response.status_code == 200, response.text
        assert [row["engagement_id"] for row in response.json()["items"]] == [older, newer]
