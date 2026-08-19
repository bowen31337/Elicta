"""Tests for the full PRD generation HTTP surface, gated on cross-meeting coverage (PRD FR-8.10)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.artifacts.models import (
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    RequirementsCoverageMatrix,
    RequirementsState,
)
from app.modules.debrief.artifacts.router import (
    build_decision_log_router,
    build_follow_up_email_router,
    build_full_prd_router,
    build_open_questions_router,
    build_project_brief_router,
)
from app.modules.debrief.pipeline.models import (
    ArtifactCitation,
    BmadAnalystChainStatus,
    BmadArtifactSet,
    ClaimProvenance,
    DecisionLogEntry,
    FillState,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
    SessionBmadAnalystChain,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_entry(section_key: str, title: str, fill_state: FillState) -> CoverageMatrixEntry:
    return CoverageMatrixEntry(section_key=section_key, title=title, fill_state=fill_state, utterance_ids=[], citations=[])


def make_matrix(
    entries: list[CoverageMatrixEntry], *, status: CoverageMatrixStatus = CoverageMatrixStatus.COMPLETE,
    session_id: str = "session-1",
) -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id=session_id,
        status=status,
        entries=entries,
        is_fully_covered=bool(entries) and all(entry.fill_state == FillState.FILLED for entry in entries),
        generated_at=FIXED,
    )


def make_artifact_set(
    decisions: list[DecisionLogEntry] | None = None, open_questions: list[OpenQuestion] | None = None
) -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=open_questions or [],
        decisions=decisions or [],
        project_brief=ProjectBriefDraft(body="draft brief", provenance=ClaimProvenance.STATED, citations=[]),
        follow_up_email=FollowUpEmailDraft(
            subject="Follow up", body="draft email", provenance=ClaimProvenance.STATED, citations=[]
        ),
    )


def make_open_question(text: str, impact_rank: int) -> OpenQuestion:
    return OpenQuestion(text=text, impact_rank=impact_rank, provenance=ClaimProvenance.STATED, citations=[])


def make_decision(text: str, provenance: ClaimProvenance) -> DecisionLogEntry:
    return DecisionLogEntry(
        text=text,
        decided_by="alice",
        provenance=provenance,
        citations=[
            ArtifactCitation(
                utterance_id="utt-1", session_id="session-1", start_seconds=0.0, end_seconds=1.0,
                speaker_tag="alice", quoted_text="quoted", original_language="en",
            )
        ],
    )


def make_requirements_state(decisions: list[DecisionLogEntry]) -> RequirementsState:
    return RequirementsState(
        engagement_id="eng-1", confirmed_requirements=[], contradictions=[], decisions=decisions, updated_at=FIXED,
    )


def make_client(
    matrices: list[RequirementsCoverageMatrix],
    *,
    threshold: float | None = None,
    requirements_states: dict[str, RequirementsState] | None = None,
    with_requirements_state: bool = True,
) -> tuple[TestClient, list[str]]:
    generate_calls: list[str] = []
    states = requirements_states or {}

    async def get_matrices(engagement_id: str) -> list[RequirementsCoverageMatrix]:
        return matrices

    async def generate(engagement_id: str) -> BmadArtifactSet:
        generate_calls.append(engagement_id)
        return make_artifact_set()

    async def get_requirements_state(engagement_id: str) -> RequirementsState | None:
        return states.get(engagement_id)

    app = FastAPI()
    kwargs = {} if threshold is None else {"threshold": threshold}
    if with_requirements_state:
        kwargs["get_requirements_state"] = get_requirements_state
    app.include_router(build_full_prd_router(get_matrices, generate, **kwargs))
    return TestClient(app), generate_calls


def test_full_coverage_across_meetings_generates_the_full_prd():
    matrices = [
        make_matrix([make_entry("timeline", "Timeline", FillState.FILLED)], session_id="meeting-1"),
        make_matrix([make_entry("budget", "Budget", FillState.FILLED)], session_id="meeting-2"),
    ]
    client, generate_calls = make_client(matrices)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 201
    assert generate_calls == ["eng-1"]
    assert response.json()["project_brief"]["body"] == "draft brief"


def test_insufficient_coverage_across_meetings_returns_409_with_an_explanation():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)]
        ),
    ]
    client, generate_calls = make_client(matrices)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 409
    assert "Budget" in response.json()["detail"]
    assert generate_calls == []


def test_an_engagement_with_no_meetings_at_all_returns_409():
    client, generate_calls = make_client([])

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 409
    assert generate_calls == []


def test_a_lower_custom_threshold_allows_generation_with_partial_coverage():
    matrices = [
        make_matrix(
            [make_entry("timeline", "Timeline", FillState.FILLED), make_entry("budget", "Budget", FillState.EMPTY)]
        ),
    ]
    client, generate_calls = make_client(matrices, threshold=0.5)

    response = client.post("/api/engagements/eng-1/prd")

    assert response.status_code == 201
    assert generate_calls == ["eng-1"]


def test_getting_requirements_state_exposes_each_decisions_inference_marker_distinctly():
    state = make_requirements_state(
        [
            make_decision("go with vendor A", ClaimProvenance.STATED),
            make_decision("timeline likely slips a month", ClaimProvenance.INFERRED),
        ]
    )
    client, _ = make_client([], requirements_states={"eng-1": state})

    response = client.get("/api/engagements/eng-1/requirements-state")

    assert response.status_code == 200
    provenances = [decision["provenance"] for decision in response.json()["decisions"]]
    assert provenances == ["stated", "inferred"]


def test_getting_requirements_state_for_an_unknown_engagement_returns_404_when_wired():
    client, _ = make_client([])

    response = client.get("/api/engagements/unknown-engagement/requirements-state")

    assert response.status_code == 404


def test_the_requirements_state_route_is_not_registered_when_get_requirements_state_is_not_supplied():
    client, _ = make_client([], with_requirements_state=False)

    response = client.get("/api/engagements/eng-1/requirements-state")

    assert response.status_code == 404
    assert response.json()["detail"] != "requirements state not found"


def make_bmad_chain(
    session_id: str = "session-1",
    *,
    status: BmadAnalystChainStatus = BmadAnalystChainStatus.COMPLETE,
    decisions: list[DecisionLogEntry] | None = None,
    open_questions: list[OpenQuestion] | None = None,
) -> SessionBmadAnalystChain:
    return SessionBmadAnalystChain(
        session_id=session_id,
        status=status,
        engine="claude-agent-sdk",
        artifacts=make_artifact_set(decisions, open_questions) if status == BmadAnalystChainStatus.COMPLETE else None,
        requested_at=FIXED,
        completed_at=FIXED,
        error=None if status == BmadAnalystChainStatus.COMPLETE else "chain run failed",
    )


def make_project_brief_client(chains: dict[str, SessionBmadAnalystChain]) -> TestClient:
    async def get_chain(session_id: str) -> SessionBmadAnalystChain | None:
        return chains.get(session_id)

    app = FastAPI()
    app.include_router(build_project_brief_router(get_chain))
    return TestClient(app)


def test_getting_a_sessions_draft_project_brief_returns_its_body_and_provenance():
    client = make_project_brief_client({"session-1": make_bmad_chain("session-1")})

    response = client.get("/api/sessions/session-1/project-brief")

    assert response.status_code == 200
    body = response.json()
    assert body["body"] == "draft brief"
    assert body["provenance"] == "stated"


def test_getting_the_draft_project_brief_for_a_session_with_no_chain_record_returns_404():
    client = make_project_brief_client({})

    response = client.get("/api/sessions/unknown-session/project-brief")

    assert response.status_code == 404
    assert response.json()["detail"] == "draft project brief not found"


def test_getting_the_draft_project_brief_for_a_session_whose_chain_run_failed_returns_404():
    client = make_project_brief_client({"session-1": make_bmad_chain("session-1", status=BmadAnalystChainStatus.FAILED)})

    response = client.get("/api/sessions/session-1/project-brief")

    assert response.status_code == 404
    assert response.json()["detail"] == "draft project brief not found"


def make_decision_log_client(chains: dict[str, SessionBmadAnalystChain]) -> TestClient:
    async def get_chain(session_id: str) -> SessionBmadAnalystChain | None:
        return chains.get(session_id)

    app = FastAPI()
    app.include_router(build_decision_log_router(get_chain))
    return TestClient(app)


def test_getting_a_sessions_decision_log_returns_what_was_agreed_and_by_whom():
    decisions = [
        make_decision("go with vendor A", ClaimProvenance.STATED),
        make_decision("timeline likely slips a month", ClaimProvenance.INFERRED),
    ]
    client = make_decision_log_client({"session-1": make_bmad_chain("session-1", decisions=decisions)})

    response = client.get("/api/sessions/session-1/decision-log")

    assert response.status_code == 200
    body = response.json()
    assert [entry["text"] for entry in body] == ["go with vendor A", "timeline likely slips a month"]
    assert [entry["decided_by"] for entry in body] == ["alice", "alice"]
    assert [entry["provenance"] for entry in body] == ["stated", "inferred"]


def test_getting_the_decision_log_for_a_session_with_no_decisions_returns_an_empty_list():
    client = make_decision_log_client({"session-1": make_bmad_chain("session-1", decisions=[])})

    response = client.get("/api/sessions/session-1/decision-log")

    assert response.status_code == 200
    assert response.json() == []


def test_getting_the_decision_log_for_a_session_with_no_chain_record_returns_404():
    client = make_decision_log_client({})

    response = client.get("/api/sessions/unknown-session/decision-log")

    assert response.status_code == 404
    assert response.json()["detail"] == "decision log not found"


def test_getting_the_decision_log_for_a_session_whose_chain_run_failed_returns_404():
    client = make_decision_log_client({"session-1": make_bmad_chain("session-1", status=BmadAnalystChainStatus.FAILED)})

    response = client.get("/api/sessions/session-1/decision-log")

    assert response.status_code == 404
    assert response.json()["detail"] == "decision log not found"


def make_open_questions_client(chains: dict[str, SessionBmadAnalystChain]) -> TestClient:
    async def get_chain(session_id: str) -> SessionBmadAnalystChain | None:
        return chains.get(session_id)

    app = FastAPI()
    app.include_router(build_open_questions_router(get_chain))
    return TestClient(app)


def test_getting_a_sessions_open_questions_returns_them_ranked_by_impact_regardless_of_chain_order():
    open_questions = [
        make_open_question("what is the go-live date", impact_rank=2),
        make_open_question("who owns data migration", impact_rank=1),
        make_open_question("is legal sign-off required", impact_rank=3),
    ]
    client = make_open_questions_client(
        {"session-1": make_bmad_chain("session-1", open_questions=open_questions)}
    )

    response = client.get("/api/sessions/session-1/open-questions")

    assert response.status_code == 200
    body = response.json()
    assert [entry["text"] for entry in body] == [
        "who owns data migration",
        "what is the go-live date",
        "is legal sign-off required",
    ]
    assert [entry["impact_rank"] for entry in body] == [1, 2, 3]


def test_getting_the_open_questions_list_for_a_session_with_no_open_questions_returns_an_empty_list():
    client = make_open_questions_client({"session-1": make_bmad_chain("session-1", open_questions=[])})

    response = client.get("/api/sessions/session-1/open-questions")

    assert response.status_code == 200
    assert response.json() == []


def test_getting_the_open_questions_list_for_a_session_with_no_chain_record_returns_404():
    client = make_open_questions_client({})

    response = client.get("/api/sessions/unknown-session/open-questions")

    assert response.status_code == 404
    assert response.json()["detail"] == "open questions list not found"


def test_getting_the_open_questions_list_for_a_session_whose_chain_run_failed_returns_404():
    client = make_open_questions_client(
        {"session-1": make_bmad_chain("session-1", status=BmadAnalystChainStatus.FAILED)}
    )

    response = client.get("/api/sessions/session-1/open-questions")

    assert response.status_code == 404
    assert response.json()["detail"] == "open questions list not found"


def make_follow_up_email_client(chains: dict[str, SessionBmadAnalystChain]) -> TestClient:
    async def get_chain(session_id: str) -> SessionBmadAnalystChain | None:
        return chains.get(session_id)

    app = FastAPI()
    app.include_router(build_follow_up_email_router(get_chain))
    return TestClient(app)


def test_getting_a_sessions_draft_follow_up_email_returns_its_subject_body_and_provenance():
    client = make_follow_up_email_client({"session-1": make_bmad_chain("session-1")})

    response = client.get("/api/sessions/session-1/follow-up-email")

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "Follow up"
    assert body["body"] == "draft email"
    assert body["provenance"] == "stated"


def test_getting_the_draft_follow_up_email_for_a_session_with_no_chain_record_returns_404():
    client = make_follow_up_email_client({})

    response = client.get("/api/sessions/unknown-session/follow-up-email")

    assert response.status_code == 404
    assert response.json()["detail"] == "draft follow-up email not found"


def test_getting_the_draft_follow_up_email_for_a_session_whose_chain_run_failed_returns_404():
    client = make_follow_up_email_client(
        {"session-1": make_bmad_chain("session-1", status=BmadAnalystChainStatus.FAILED)}
    )

    response = client.get("/api/sessions/session-1/follow-up-email")

    assert response.status_code == 404
    assert response.json()["detail"] == "draft follow-up email not found"
