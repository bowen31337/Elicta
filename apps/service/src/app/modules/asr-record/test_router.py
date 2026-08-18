"""Tests for the record-path re-transcription HTTP surface.

Loaded via `importlib.import_module` with the full dotted path rather than
`from .models import ...` / `from .router import ...`: this package's
directory (`asr-record`) is not a valid Python identifier, and pytest's
default test-collection import mode cannot resolve a relative import inside
it (it works fine at real runtime via `app.module_loader`, which uses the
same `importlib.import_module` mechanism this file uses).
"""

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

_models = importlib.import_module("app.modules.asr-record.models")
_router = importlib.import_module("app.modules.asr-record.router")

BatchTranscriptionOutput = _models.BatchTranscriptionOutput
RecordPathTranscript = _models.RecordPathTranscript
TranscriptionStatus = _models.TranscriptionStatus
TranscriptSegment = _models.TranscriptSegment
build_record_path_router = _router.build_record_path_router


def make_client(
    *,
    engine: str = "highest-accuracy-engine",
    fail: bool = False,
    vocabulary: list[str] | None = None,
) -> tuple[TestClient, dict[str, RecordPathTranscript], list[list[str]]]:
    store: dict[str, RecordPathTranscript] = {}
    sent_keyterms: list[list[str]] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        sent_keyterms.append(keyterms)
        if fail:
            raise RuntimeError("vendor engine unavailable")
        return BatchTranscriptionOutput(
            engine=engine,
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello")
            ],
            text="hello",
        )

    async def get_vocabulary(session_id: str) -> list[str]:
        return vocabulary if vocabulary is not None else []

    async def save(transcript: RecordPathTranscript) -> None:
        store[transcript.session_id] = transcript

    async def get(session_id: str) -> RecordPathTranscript | None:
        return store.get(session_id)

    app = FastAPI()
    app.include_router(
        build_record_path_router(transcribe, get_vocabulary, save, get)
    )
    return TestClient(app, raise_server_exceptions=False), store, sent_keyterms


def test_posting_triggers_batch_transcription_and_returns_201():
    client, _, _ = make_client()

    response = client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["status"] == "complete"
    assert body["text"] == "hello"
    assert body["engine"] == "highest-accuracy-engine"


def test_posting_sends_the_engagement_vocabulary_as_keyterms():
    client, _, sent_keyterms = make_client(
        vocabulary=["Acme Corp", "Project Nightingale"]
    )

    client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert sent_keyterms == [["Acme Corp", "Project Nightingale"]]


def test_posting_persists_the_transcript_so_it_can_be_fetched_afterwards():
    client, store, _ = make_client()

    client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert "session-1" in store
    assert store["session-1"].status == TranscriptionStatus.COMPLETE

    response = client.get("/api/sessions/session-1/record-path-transcript")
    assert response.status_code == 200
    assert response.json()["session_id"] == "session-1"


def test_missing_audio_ref_is_rejected():
    client, _, _ = make_client()

    response = client.post(
        "/api/sessions/session-1/record-path-transcript", json={"audio_ref": ""}
    )

    assert response.status_code == 422


def test_getting_a_session_with_no_transcript_yet_returns_404():
    client, _, _ = make_client()

    response = client.get("/api/sessions/unknown-session/record-path-transcript")

    assert response.status_code == 404


def test_a_failed_batch_run_still_persists_a_failed_record():
    client, store, _ = make_client(fail=True)

    response = client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert response.status_code == 500
    assert store["session-1"].status == TranscriptionStatus.FAILED
    assert store["session-1"].error == "vendor engine unavailable"
