"""Tests for the engagement standing state HTTP surface (PRD FR-4.8, FR-8.9)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.artifacts.models import RequirementsState
from app.modules.engagement.state.models import InheritedOpenQuestion
from app.modules.engagement.state.router import build_engagement_state_router


def make_client(
    inherited_open_questions: dict[str, list[InheritedOpenQuestion]] | None = None,
    requirements_states: dict[str, RequirementsState] | None = None,
) -> TestClient:
    inherited_open_questions = inherited_open_questions or {}
    requirements_states = requirements_states or {}

    async def get_inherited_open_questions(engagement_id: str) -> list[InheritedOpenQuestion]:
        return inherited_open_questions.get(engagement_id, [])

    async def get_requirements_state(engagement_id: str) -> RequirementsState | None:
        return requirements_states.get(engagement_id)

    app = FastAPI()
    app.include_router(
        build_engagement_state_router(get_inherited_open_questions, get_requirements_state)
    )
    return TestClient(app)


def make_requirements_state(engagement_id: str = "engagement-1") -> RequirementsState:
    return RequirementsState(
        engagement_id=engagement_id,
        confirmed_requirements=[],
        contradictions=[],
        decisions=[],
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_get_engagement_state_returns_200_for_an_engagement_with_no_prior_meetings():
    client = make_client()

    response = client.get("/api/engagements/engagement-1/state")

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "engagement-1"
    assert body["inherited_open_questions"] == []
    assert body["requirements_state"] is None


def test_get_engagement_state_returns_the_inherited_open_questions_ranked_by_impact():
    client = make_client(
        inherited_open_questions={
            "engagement-1": [
                InheritedOpenQuestion(text="which regions launch first?", impact_rank=2),
                InheritedOpenQuestion(text="who owns budget sign-off?", impact_rank=1),
            ]
        }
    )

    response = client.get("/api/engagements/engagement-1/state")

    assert response.status_code == 200
    questions = response.json()["inherited_open_questions"]
    assert [q["text"] for q in questions] == [
        "who owns budget sign-off?",
        "which regions launch first?",
    ]


def test_get_engagement_state_returns_the_requirements_state():
    state = make_requirements_state("engagement-1")
    client = make_client(requirements_states={"engagement-1": state})

    response = client.get("/api/engagements/engagement-1/state")

    assert response.status_code == 200
    body = response.json()
    assert body["requirements_state"]["engagement_id"] == "engagement-1"


def test_get_engagement_state_combines_both_pieces_of_state_in_one_response():
    client = make_client(
        inherited_open_questions={
            "engagement-1": [InheritedOpenQuestion(text="who owns budget sign-off?", impact_rank=1)]
        },
        requirements_states={"engagement-1": make_requirements_state("engagement-1")},
    )

    response = client.get("/api/engagements/engagement-1/state")

    assert response.status_code == 200
    body = response.json()
    assert body["inherited_open_questions"][0]["text"] == "who owns budget sign-off?"
    assert body["requirements_state"]["engagement_id"] == "engagement-1"


def test_get_engagement_state_for_an_unknown_engagement_still_returns_200():
    client = make_client(
        inherited_open_questions={"engagement-1": [InheritedOpenQuestion(text="q", impact_rank=1)]},
        requirements_states={"engagement-1": make_requirements_state("engagement-1")},
    )

    response = client.get("/api/engagements/unknown-engagement/state")

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "unknown-engagement"
    assert body["inherited_open_questions"] == []
    assert body["requirements_state"] is None
