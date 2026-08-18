"""Happy-path 2xx and documented-4xx coverage for engagement + record-path transcription."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import Backend


def test_create_engagement_returns_201(client: TestClient) -> None:
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Corp",
            "sector": "Manufacturing",
            "commercial_context": "Multi-year cost reduction programme",
        },
    )

    assert response.status_code == 201
    assert response.json()["engagement_id"]


def test_create_engagement_blank_field_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/engagements",
        json={"client_organisation": "", "sector": "Manufacturing", "commercial_context": "x"},
    )

    assert response.status_code == 422


def test_record_path_transcript_round_trip_201_then_200(client: TestClient) -> None:
    post_response = client.post(
        "/api/sessions/s1/record-path-transcript", json={"audio_ref": "audio://s1"}
    )

    assert post_response.status_code == 201
    body = post_response.json()
    assert len(body) == 2
    assert {t["engine"] for t in body} == {"engine-a", "engine-b"}
    assert all(t["status"] == "complete" for t in body)

    get_response = client.get("/api/sessions/s1/record-path-transcript")

    assert get_response.status_code == 200
    assert len(get_response.json()) == 2


def test_record_path_transcript_blank_audio_ref_returns_422(client: TestClient) -> None:
    response = client.post("/api/sessions/s1/record-path-transcript", json={"audio_ref": ""})

    assert response.status_code == 422


def test_get_record_path_transcript_for_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/never-posted/record-path-transcript")

    assert response.status_code == 404


def test_record_path_alignment_round_trip_returns_200(client: TestClient) -> None:
    client.post("/api/sessions/s2/record-path-transcript", json={"audio_ref": "audio://s2"})

    response = client.get("/api/sessions/s2/record-path-alignment")

    assert response.status_code == 200
    assert response.json()["session_id"] == "s2"


def test_get_record_path_alignment_for_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/never-posted/record-path-alignment")

    assert response.status_code == 404


def test_start_meeting_record_path_transcription_returns_202(client: TestClient, backend: Backend) -> None:
    response = client.post(
        "/api/meetings/mtg-1/record/transcribe", json={"audio_ref": "audio://mtg-1"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert set(body["engine_lineages"]) == {"engine-a", "engine-b"}
    assert body["job_id"] in backend.transcription_jobs


def test_get_meeting_record_divergences_returns_200(client: TestClient, backend: Backend) -> None:
    import importlib

    asr_models = importlib.import_module("app.modules.asr-record.models")
    backend.session_alignments["mtg-2"] = asr_models.SessionAlignment(
        session_id="mtg-2",
        reference_engine="engine-a",
        other_engine="engine-b",
        spans=[
            asr_models.AlignedSpan(
                start_seconds=0.0,
                end_seconds=1.0,
                reference_engine="engine-a",
                reference_text="hello there",
                other_engine="engine-b",
                other_text="hello there",
                agreement_score=1.0,
                is_divergent=False,
            ),
            asr_models.AlignedSpan(
                start_seconds=1.0,
                end_seconds=2.0,
                reference_engine="engine-a",
                reference_text="quarterly revenue",
                other_engine="engine-b",
                other_text="quarterly refund",
                agreement_score=0.5,
                is_divergent=True,
            ),
        ],
        computed_at="2026-01-01T00:00:00Z",
    )

    response = client.get("/api/meetings/mtg-2/record/divergences")

    assert response.status_code == 200
    spans = response.json()["spans"]
    assert len(spans) == 1
    assert spans[0]["is_divergent"] is True


def test_get_meeting_record_divergences_for_unknown_meeting_returns_404(client: TestClient) -> None:
    response = client.get("/api/meetings/never-posted/record/divergences")

    assert response.status_code == 404
