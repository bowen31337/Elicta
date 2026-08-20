"""Happy-path 2xx and documented-4xx coverage for the debrief modules.

Covers: debrief/session (conversation), debrief/pipeline (citation rows),
debrief/api (artifact list/detail), debrief/artifacts (full PRD generation,
requirements state, project brief, decision log, open questions, follow-up
email).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.debrief.api.models import ArtifactSummary, ArtifactType
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageMatrixEntry,
    CoverageMatrixStatus,
    FillState,
    RequirementsCoverageMatrix,
    RequirementsState,
)
from app.modules.debrief.pipeline.models import (
    ArtifactCitation,
    BmadAnalystChainStatus,
    BmadArtifactSet,
    ClaimProvenance,
    DecisionLogEntry,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
    SessionBmadAnalystChain,
)
from fastapi.testclient import TestClient

from conftest import Backend

_NOW = datetime.now(timezone.utc)


def _citation() -> ArtifactCitation:
    return ArtifactCitation(
        utterance_id="u1",
        session_id="s1",
        start_seconds=0.0,
        end_seconds=1.0,
        speaker_tag="speaker-1",
        quoted_text="we need this by Q3",
        original_language="en",
    )


def test_start_debrief_session_returns_201(client: TestClient) -> None:
    response = client.post("/api/meetings/m1/debrief/start")

    assert response.status_code == 201
    assert response.json()["meeting_id"] == "m1"
    assert response.json()["status"] == "open"


def test_send_debrief_message_without_an_engine_returns_503(client: TestClient) -> None:
    """This app is built with no inference engine, so the conversation cannot answer.

    It used to assert a 200 with an assistant turn, which passed because the
    composition root replied "ack: {message}" itself. Both halves were true
    and the feature was not: an operator saw a stub rendered as an answer.
    An app with no model configured must say so — the conversation that does
    answer from an engine is covered in `test_debrief_conversation_seam.py`.
    """

    client.post("/api/meetings/m1/debrief/start")

    response = client.post("/api/meetings/m1/debrief/message", json={"message": "what changed?"})

    assert response.status_code == 503
    assert "configured" in response.json()["detail"].lower()


def test_send_debrief_message_missing_body_returns_422(client: TestClient) -> None:
    client.post("/api/meetings/m1/debrief/start")

    response = client.post("/api/meetings/m1/debrief/message", json={})

    assert response.status_code == 422


def test_write_citation_row_returns_201(client: TestClient, backend: Backend) -> None:
    response = client.post(
        "/api/sessions/s1/citations",
        json={
            "session_id": "s1",
            "claim_kind": "decision",
            "claim_index": 0,
            "utterance_id": "u1",
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "speaker_tag": "speaker-1",
            "quoted_text": "we agreed on Q3",
            "original_language": "en",
        },
    )

    assert response.status_code == 201
    assert len(backend.citation_rows) == 1


def test_write_citation_row_missing_field_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/sessions/s1/citations",
        json={
            "session_id": "s1",
            "claim_kind": "decision",
            "claim_index": 0,
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "speaker_tag": "speaker-1",
            "quoted_text": "we agreed on Q3",
            "original_language": "en",
        },
    )

    assert response.status_code == 422


def test_list_meeting_artifacts_returns_200(client: TestClient, backend: Backend) -> None:
    backend.meeting_artifacts["m1"] = [
        ArtifactSummary(artifact_type=ArtifactType.TRANSCRIPT, generated_at=_NOW)
    ]

    response = client.get("/api/meetings/m1/artifacts")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_artifact_detail_returns_200(client: TestClient, backend: Backend) -> None:
    from app.modules.debrief.api.models import ArtifactDetail

    backend.artifacts_by_id["a1"] = ArtifactDetail(
        id="a1",
        session_id="s1",
        artifact_type=ArtifactType.DECISION_LOG,
        artifact_language="en",
        body={"decisions": []},
        generated_at=_NOW,
    )

    response = client.get("/api/artifacts/a1")

    assert response.status_code == 200
    assert response.json()["id"] == "a1"


def test_get_artifact_detail_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/artifacts/unknown")

    assert response.status_code == 404


def _fully_covered_matrix() -> RequirementsCoverageMatrix:
    return RequirementsCoverageMatrix(
        session_id="s1",
        status=CoverageMatrixStatus.COMPLETE,
        entries=[
            CoverageMatrixEntry(
                section_key="scope",
                title="Scope",
                fill_state=FillState.FILLED,
                utterance_ids=["u1"],
                citations=[
                    CoverageCitation(
                        session_id="s1",
                        engine="engine-a",
                        start_seconds=0.0,
                        end_seconds=1.0,
                        quoted_text="the scope is Q3 rollout",
                        transcript_completed_at=_NOW,
                    )
                ],
            )
        ],
        is_fully_covered=True,
        generated_at=_NOW,
    )


def _artifact_set() -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=[
            OpenQuestion(text="q1", impact_rank=2, provenance=ClaimProvenance.STATED, citations=[_citation()]),
            OpenQuestion(text="q0", impact_rank=1, provenance=ClaimProvenance.STATED, citations=[_citation()]),
        ],
        decisions=[
            DecisionLogEntry(
                text="ship by Q3", decided_by="client", provenance=ClaimProvenance.STATED, citations=[_citation()]
            )
        ],
        project_brief=ProjectBriefDraft(body="brief", provenance=ClaimProvenance.STATED, citations=[_citation()]),
        follow_up_email=FollowUpEmailDraft(
            subject="Next steps", body="body", provenance=ClaimProvenance.STATED, citations=[_citation()]
        ),
    )


def test_generate_full_prd_returns_201_when_coverage_clears_threshold(
    client: TestClient, backend: Backend
) -> None:
    backend.coverage_matrices["e1"] = [_fully_covered_matrix()]
    backend.prd_to_generate = _artifact_set()

    response = client.post("/api/engagements/e1/prd")

    assert response.status_code == 201
    assert backend.generated_prds == ["e1"]


def test_generate_full_prd_returns_409_when_coverage_incomplete(client: TestClient) -> None:
    response = client.post("/api/engagements/no-coverage/prd")

    assert response.status_code == 409
    assert "coverage" in response.json()["detail"]


def test_get_requirements_state_returns_200(client: TestClient, backend: Backend) -> None:
    backend.requirements_states["e1"] = RequirementsState(
        engagement_id="e1", confirmed_requirements=[], contradictions=[], decisions=[], updated_at=_NOW
    )

    response = client.get("/api/engagements/e1/requirements-state")

    assert response.status_code == 200
    assert response.json()["engagement_id"] == "e1"


def test_get_requirements_state_unknown_engagement_returns_404(client: TestClient) -> None:
    response = client.get("/api/engagements/unknown/requirements-state")

    assert response.status_code == 404


def _complete_chain() -> SessionBmadAnalystChain:
    return SessionBmadAnalystChain(
        session_id="s1",
        status=BmadAnalystChainStatus.COMPLETE,
        engine="claude",
        artifacts=_artifact_set(),
        requested_at=_NOW,
        completed_at=_NOW,
    )


def test_get_project_brief_returns_200(client: TestClient, backend: Backend) -> None:
    backend.bmad_chains["s1"] = _complete_chain()

    response = client.get("/api/sessions/s1/project-brief")

    assert response.status_code == 200
    assert response.json()["body"] == "brief"


def test_get_project_brief_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/unknown/project-brief")

    assert response.status_code == 404


def test_get_decision_log_returns_200(client: TestClient, backend: Backend) -> None:
    backend.bmad_chains["s1"] = _complete_chain()

    response = client.get("/api/sessions/s1/decision-log")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_decision_log_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/unknown/decision-log")

    assert response.status_code == 404


def test_get_open_questions_returns_200_sorted_by_impact_rank(client: TestClient, backend: Backend) -> None:
    backend.bmad_chains["s1"] = _complete_chain()

    response = client.get("/api/sessions/s1/open-questions")

    assert response.status_code == 200
    ranks = [q["impact_rank"] for q in response.json()]
    assert ranks == sorted(ranks)


def test_get_open_questions_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/unknown/open-questions")

    assert response.status_code == 404


def test_get_follow_up_email_returns_200(client: TestClient, backend: Backend) -> None:
    backend.bmad_chains["s1"] = _complete_chain()

    response = client.get("/api/sessions/s1/follow-up-email")

    assert response.status_code == 200
    assert response.json()["subject"] == "Next steps"


def test_get_follow_up_email_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/unknown/follow-up-email")

    assert response.status_code == 404
