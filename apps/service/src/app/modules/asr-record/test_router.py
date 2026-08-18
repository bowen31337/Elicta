"""Tests for the record-path re-transcription HTTP surface.

Loaded via `importlib.import_module` with the full dotted path rather than
`from .models import ...` / `from .router import ...`: this package's
directory (`asr-record`) is not a valid Python identifier, and pytest's
default test-collection import mode cannot resolve a relative import inside
it (it works fine at real runtime via `app.module_loader`, which uses the
same `importlib.import_module` mechanism this file uses).
"""

import asyncio
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

_models = importlib.import_module("app.modules.asr-record.models")
_router = importlib.import_module("app.modules.asr-record.router")

BatchTranscriptionOutput = _models.BatchTranscriptionOutput
RecordPathTranscript = _models.RecordPathTranscript
RecordPathTranscriptionJob = _models.RecordPathTranscriptionJob
TranscriptionJobStatus = _models.TranscriptionJobStatus
TranscriptionStatus = _models.TranscriptionStatus
TranscriptSegment = _models.TranscriptSegment
build_record_path_router = _router.build_record_path_router
build_meeting_transcription_router = _router.build_meeting_transcription_router


def make_engine(name: str, *, fail: bool = False):
    sent_keyterms: list[list[str]] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        sent_keyterms.append(keyterms)
        if fail:
            raise RuntimeError(f"{name} vendor engine unavailable")
        return BatchTranscriptionOutput(
            engine=name,
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello")
            ],
            text=f"hello from {name}",
        )

    return (name, transcribe), sent_keyterms


def make_client(
    *,
    fail_a: bool = False,
    fail_b: bool = False,
    vocabulary: list[str] | None = None,
) -> tuple[TestClient, dict[str, list[RecordPathTranscript]], list[list[list[str]]]]:
    store: dict[str, list[RecordPathTranscript]] = {}

    engine_a, keyterms_a = make_engine("engine-a", fail=fail_a)
    engine_b, keyterms_b = make_engine("engine-b", fail=fail_b)
    engines = [engine_a, engine_b]

    async def get_vocabulary(session_id: str) -> list[str]:
        return vocabulary if vocabulary is not None else []

    async def save(transcript: RecordPathTranscript) -> None:
        store.setdefault(transcript.session_id, []).append(transcript)

    async def get(session_id: str) -> list[RecordPathTranscript]:
        return store.get(session_id, [])

    app = FastAPI()
    app.include_router(
        build_record_path_router(engines, get_vocabulary, save, get)
    )
    return TestClient(app, raise_server_exceptions=False), store, [keyterms_a, keyterms_b]


def test_posting_triggers_both_batch_engines_and_returns_201():
    client, _, _ = make_client()

    response = client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body) == 2
    assert {t["engine"] for t in body} == {"engine-a", "engine-b"}
    assert all(t["session_id"] == "session-1" for t in body)
    assert all(t["status"] == "complete" for t in body)


def test_posting_sends_the_engagement_vocabulary_as_keyterms_to_both_engines():
    client, _, keyterms = make_client(
        vocabulary=["Acme Corp", "Project Nightingale"]
    )

    client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert keyterms[0] == [["Acme Corp", "Project Nightingale"]]
    assert keyterms[1] == [["Acme Corp", "Project Nightingale"]]


def test_posting_persists_one_transcript_per_engine_so_they_can_be_fetched_afterwards():
    client, store, _ = make_client()

    client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert len(store["session-1"]) == 2
    assert all(t.status == TranscriptionStatus.COMPLETE for t in store["session-1"])

    response = client.get("/api/sessions/session-1/record-path-transcript")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(t["session_id"] == "session-1" for t in body)


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


def test_one_engine_failing_still_persists_a_failed_record_for_it_and_a_complete_one_for_the_other():
    client, store, _ = make_client(fail_a=True)

    response = client.post(
        "/api/sessions/session-1/record-path-transcript",
        json={"audio_ref": "recordings/session-1.wav"},
    )

    assert response.status_code == 201
    by_engine = {t.engine: t for t in store["session-1"]}
    assert by_engine["engine-a"].status == TranscriptionStatus.FAILED
    assert by_engine["engine-a"].error == "engine-a vendor engine unavailable"
    assert by_engine["engine-b"].status == TranscriptionStatus.COMPLETE


def make_meeting_client(
    *, fail_a: bool = False, fail_b: bool = False, vocabulary: list[str] | None = None
) -> tuple[
    TestClient, dict[str, list[RecordPathTranscript]], list[RecordPathTranscriptionJob], list
]:
    transcript_store: dict[str, list[RecordPathTranscript]] = {}
    job_store: list[RecordPathTranscriptionJob] = []
    scheduled: list = []

    engine_a, _ = make_engine("engine-a", fail=fail_a)
    engine_b, _ = make_engine("engine-b", fail=fail_b)
    engines = [engine_a, engine_b]

    async def get_vocabulary(meeting_id: str) -> list[str]:
        return vocabulary if vocabulary is not None else []

    async def save_transcript(transcript: RecordPathTranscript) -> None:
        transcript_store.setdefault(transcript.session_id, []).append(transcript)

    async def save_job(job: RecordPathTranscriptionJob) -> None:
        job_store.append(job)

    def schedule(work) -> None:
        scheduled.append(work)

    app = FastAPI()
    app.include_router(
        build_meeting_transcription_router(
            engines, get_vocabulary, save_transcript, save_job, schedule
        )
    )
    return (
        TestClient(app, raise_server_exceptions=False),
        transcript_store,
        job_store,
        scheduled,
    )


def test_starting_a_meeting_transcription_returns_202_with_a_job_id():
    client, _, _, _ = make_meeting_client()

    response = client.post(
        "/api/meetings/meeting-1/record/transcribe",
        json={"audio_ref": "recordings/meeting-1.wav"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["meeting_id"] == "meeting-1"
    assert body["status"] == "queued"
    assert body["engine_lineages"] == ["engine-a", "engine-b"]


def test_starting_a_meeting_transcription_does_not_block_on_the_batch_run():
    client, transcript_store, job_store, scheduled = make_meeting_client()

    response = client.post(
        "/api/meetings/meeting-1/record/transcribe",
        json={"audio_ref": "recordings/meeting-1.wav"},
    )

    assert response.status_code == 202
    assert transcript_store == {}
    assert job_store[-1].status == TranscriptionJobStatus.QUEUED
    assert len(scheduled) == 1


def test_missing_audio_ref_is_rejected_for_meeting_transcription():
    client, _, _, _ = make_meeting_client()

    response = client.post(
        "/api/meetings/meeting-1/record/transcribe", json={"audio_ref": ""}
    )

    assert response.status_code == 422


def test_running_the_scheduled_meeting_work_persists_one_transcript_per_engine():
    client, transcript_store, job_store, scheduled = make_meeting_client()

    client.post(
        "/api/meetings/meeting-1/record/transcribe",
        json={"audio_ref": "recordings/meeting-1.wav"},
    )

    asyncio.run(scheduled[0]())

    assert len(transcript_store["meeting-1"]) == 2
    assert {t.engine for t in transcript_store["meeting-1"]} == {"engine-a", "engine-b"}
    assert job_store[-1].status == TranscriptionJobStatus.COMPLETE
