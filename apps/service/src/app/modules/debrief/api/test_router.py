from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.api.models import ArtifactSummary, ArtifactType
from app.modules.debrief.api.router import build_meeting_artifacts_router


def make_client(
    artifacts: list[ArtifactSummary] | None = None,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def get_artifacts(meeting_id: str) -> list[ArtifactSummary]:
        received.append(meeting_id)
        return artifacts if artifacts is not None else []

    app = FastAPI()
    app.include_router(build_meeting_artifacts_router(get_artifacts))
    return TestClient(app), received


def test_listing_artifacts_returns_200_with_type_and_generated_at():
    generated_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    client, _ = make_client(
        artifacts=[
            ArtifactSummary(artifact_type=ArtifactType.TRANSCRIPT, generated_at=generated_at),
            ArtifactSummary(artifact_type=ArtifactType.OPEN_QUESTIONS, generated_at=generated_at),
        ]
    )

    response = client.get("/api/meetings/m1/artifacts")

    assert response.status_code == 200
    assert response.json() == [
        {"artifact_type": "transcript", "generated_at": "2026-08-18T12:00:00Z"},
        {"artifact_type": "open_questions", "generated_at": "2026-08-18T12:00:00Z"},
    ]


def test_listing_artifacts_passes_meeting_id_through():
    client, received = make_client()

    client.get("/api/meetings/m-42/artifacts")

    assert received == ["m-42"]


def test_meeting_with_no_artifacts_returns_200_with_empty_list():
    client, _ = make_client(artifacts=[])

    response = client.get("/api/meetings/m1/artifacts")

    assert response.status_code == 200
    assert response.json() == []
