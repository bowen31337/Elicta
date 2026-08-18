from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.debrief.api.models import (
    ArtifactDetail,
    ArtifactSummary,
    ArtifactType,
    MeetingAttendee,
    MeetingCoverageSummary,
    MeetingDetail,
)
from app.modules.debrief.api.router import (
    build_artifact_detail_router,
    build_meeting_artifacts_router,
    build_meeting_detail_router,
)


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


def make_meeting_detail_client(
    meeting: MeetingDetail | None,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def get_meeting_detail(meeting_id: str) -> MeetingDetail | None:
        received.append(meeting_id)
        return meeting

    app = FastAPI()
    app.include_router(build_meeting_detail_router(get_meeting_detail))
    return TestClient(app), received


def make_detail_client(
    artifact: ArtifactDetail | None,
) -> tuple[TestClient, list[str]]:
    received: list[str] = []

    async def get_artifact(artifact_id: str) -> ArtifactDetail | None:
        received.append(artifact_id)
        return artifact

    app = FastAPI()
    app.include_router(build_artifact_detail_router(get_artifact))
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


def test_getting_artifact_by_id_returns_200_with_body_and_expanded_citations():
    generated_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    artifact = ArtifactDetail(
        id="a-1",
        session_id="m1",
        artifact_type=ArtifactType.OPEN_QUESTIONS,
        artifact_language="en",
        body={
            "open_questions": [
                {
                    "text": "What is the rollout timeline?",
                    "impact_rank": 1,
                    "provenance": "stated",
                    "citations": [
                        {
                            "utterance_id": "u-1",
                            "session_id": "m1",
                            "start_seconds": 12.0,
                            "end_seconds": 14.5,
                            "speaker_tag": "client",
                            "quoted_text": "We need this live by Q4.",
                            "original_language": "en",
                            "translated_text": None,
                        }
                    ],
                }
            ]
        },
        generated_at=generated_at,
    )
    client, received = make_detail_client(artifact)

    response = client.get("/api/artifacts/a-1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "a-1"
    assert body["session_id"] == "m1"
    assert body["artifact_type"] == "open_questions"
    assert body["generated_at"] == "2026-08-18T12:00:00Z"
    citation = body["body"]["open_questions"][0]["citations"][0]
    assert citation["utterance_id"] == "u-1"
    assert citation["quoted_text"] == "We need this live by Q4."
    assert received == ["a-1"]


def test_getting_unknown_artifact_id_returns_404():
    client, received = make_detail_client(None)

    response = client.get("/api/artifacts/missing")

    assert response.status_code == 404
    assert received == ["missing"]


def test_getting_meeting_returns_200_with_attendees_coverage_and_nudge_count():
    meeting = MeetingDetail(
        meeting_id="m1",
        engagement_id="e1",
        state="completed",
        capture_mode="record_path",
        scheduled_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        attendees=[
            MeetingAttendee(id="a-1", display_name="Jordan Lee", role="Sponsor"),
        ],
        coverage_summary=MeetingCoverageSummary(
            filled_sections=4, total_sections=6, is_fully_covered=False
        ),
        nudge_count=3,
    )
    client, received = make_meeting_detail_client(meeting)

    response = client.get("/api/meetings/m1")

    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == "m1"
    assert body["attendees"] == [
        {
            "id": "a-1",
            "display_name": "Jordan Lee",
            "role": "Sponsor",
            "business_function": None,
            "decision_authority": None,
            "domain_expertise": [],
        }
    ]
    assert body["coverage_summary"] == {
        "filled_sections": 4,
        "total_sections": 6,
        "is_fully_covered": False,
    }
    assert body["nudge_count"] == 3
    assert received == ["m1"]


def test_getting_unknown_meeting_id_returns_404():
    client, received = make_meeting_detail_client(None)

    response = client.get("/api/meetings/missing")

    assert response.status_code == 404
    assert received == ["missing"]


def test_getting_meeting_with_no_coverage_run_or_nudges_returns_200_with_null_summary_and_zero_count():
    meeting = MeetingDetail(
        meeting_id="m2",
        engagement_id="e1",
        state="planned",
        capture_mode="live",
        scheduled_at=None,
        attendees=[],
        coverage_summary=None,
        nudge_count=0,
    )
    client, _ = make_meeting_detail_client(meeting)

    response = client.get("/api/meetings/m2")

    assert response.status_code == 200
    body = response.json()
    assert body["attendees"] == []
    assert body["coverage_summary"] is None
    assert body["nudge_count"] == 0
    assert body["scheduled_at"] is None
