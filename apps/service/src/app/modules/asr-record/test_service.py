"""Tests for the record-path batch re-transcription orchestrator.

Loaded via `importlib.import_module` with the full dotted path rather than
`from .service import ...`: this package's directory (`asr-record`) is not a
valid Python identifier, and pytest's default test-collection import mode
cannot resolve a relative import inside such a directory (it works fine at
real runtime via `app.module_loader`, which uses the same
`importlib.import_module` mechanism this file uses).
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import pytest

_models = importlib.import_module("app.modules.asr-record.models")
_service = importlib.import_module("app.modules.asr-record.service")

BatchTranscriptionOutput = _models.BatchTranscriptionOutput
RecordPathTranscript = _models.RecordPathTranscript
RecordPathTranscriptionJob = _models.RecordPathTranscriptionJob
TranscriptionJobStatus = _models.TranscriptionJobStatus
TranscriptionStatus = _models.TranscriptionStatus
TranscriptSegment = _models.TranscriptSegment
run_record_path_transcription = _service.run_record_path_transcription
start_record_path_transcription_job = _service.start_record_path_transcription_job


def make_output(
    engine: str = "highest-accuracy-engine",
    text: str = "the full session transcript",
) -> BatchTranscriptionOutput:
    return BatchTranscriptionOutput(
        engine=engine,
        segments=[
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="the full"),
            TranscriptSegment(
                start_seconds=1.5, end_seconds=3.0, text="session transcript"
            ),
        ],
        text=text,
    )


def make_engine(name: str, *, fail: bool = False, text: str | None = None):
    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        if fail:
            raise RuntimeError(f"{name} vendor engine timed out")
        return make_output(engine=name, text=text or f"transcript from {name}")

    return (name, transcribe)


def test_a_successful_run_persists_a_complete_transcript_per_engine():
    saved: list[RecordPathTranscript] = []

    engines = [make_engine("engine-a"), make_engine("engine-b")]

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        return ["Acme Corp", "Project Nightingale"]

    results = asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", engines, save, get_vocabulary
        )
    )

    assert len(results) == 2
    assert {r.engine for r in results} == {"engine-a", "engine-b"}
    for result in results:
        assert result.status == TranscriptionStatus.COMPLETE
        assert result.session_id == "session-1"
        assert result.error is None
    assert sorted(saved, key=lambda t: t.engine) == sorted(
        results, key=lambda t: t.engine
    )


def test_the_two_engines_run_independently_one_failing_does_not_affect_the_other():
    saved: list[RecordPathTranscript] = []

    engines = [make_engine("engine-a", fail=True), make_engine("engine-b")]

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        return []

    results = asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", engines, save, get_vocabulary
        )
    )

    by_engine = {r.engine: r for r in results}
    assert by_engine["engine-a"].status == TranscriptionStatus.FAILED
    assert by_engine["engine-a"].error == "engine-a vendor engine timed out"
    assert by_engine["engine-b"].status == TranscriptionStatus.COMPLETE
    assert by_engine["engine-b"].error is None
    assert len(saved) == 2


def test_the_engagement_vocabulary_is_sent_as_keyterms_on_every_engines_request():
    sent_keyterms: list[list[str]] = []

    async def transcribe_a(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        sent_keyterms.append(keyterms)
        return make_output(engine="engine-a")

    async def transcribe_b(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        sent_keyterms.append(keyterms)
        return make_output(engine="engine-b")

    engines = [("engine-a", transcribe_a), ("engine-b", transcribe_b)]

    async def save(transcript: RecordPathTranscript) -> None:
        pass

    async def get_vocabulary(session_id: str) -> list[str]:
        return ["Acme Corp", "Project Nightingale", "SSO"]

    asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", engines, save, get_vocabulary
        )
    )

    assert sent_keyterms == [
        ["Acme Corp", "Project Nightingale", "SSO"],
        ["Acme Corp", "Project Nightingale", "SSO"],
    ]


def test_requested_at_is_deterministic_when_supplied():
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engines = [make_engine("engine-a"), make_engine("engine-b")]

    async def save(transcript: RecordPathTranscript) -> None:
        pass

    async def get_vocabulary(session_id: str) -> list[str]:
        return []

    results = asyncio.run(
        run_record_path_transcription(
            "session-1",
            "recordings/session-1.wav",
            engines,
            save,
            get_vocabulary,
            requested_at=fixed,
        )
    )

    for result in results:
        assert result.requested_at == fixed
        assert result.completed_at >= fixed


def test_both_engines_failing_persists_two_failed_transcripts_without_raising():
    saved: list[RecordPathTranscript] = []
    engines = [
        make_engine("engine-a", fail=True),
        make_engine("engine-b", fail=True),
    ]

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        return []

    results = asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", engines, save, get_vocabulary
        )
    )

    assert len(results) == 2
    assert all(r.status == TranscriptionStatus.FAILED for r in results)
    assert len(saved) == 2


def test_a_vocabulary_lookup_failure_persists_a_failed_transcript_per_engine_and_reraises():
    saved: list[RecordPathTranscript] = []
    engines = [make_engine("engine-a"), make_engine("engine-b")]

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        raise RuntimeError("engagement lookup unavailable")

    with pytest.raises(RuntimeError, match="engagement lookup unavailable"):
        asyncio.run(
            run_record_path_transcription(
                "session-1", "recordings/session-1.wav", engines, save, get_vocabulary
            )
        )

    assert len(saved) == 2
    assert {s.engine for s in saved} == {"engine-a", "engine-b"}
    assert all(s.status == TranscriptionStatus.FAILED for s in saved)
    assert all(s.error == "engagement lookup unavailable" for s in saved)


def make_job_deps(*, fail_a: bool = False, fail_b: bool = False):
    saved_transcripts: list[RecordPathTranscript] = []
    saved_jobs: list[RecordPathTranscriptionJob] = []
    scheduled: list = []

    engines = [
        make_engine("engine-a", fail=fail_a),
        make_engine("engine-b", fail=fail_b),
    ]

    async def get_vocabulary(meeting_id: str) -> list[str]:
        return []

    async def save_transcript(transcript: RecordPathTranscript) -> None:
        saved_transcripts.append(transcript)

    async def save_job(job: RecordPathTranscriptionJob) -> None:
        saved_jobs.append(job)

    def schedule(work) -> None:
        scheduled.append(work)

    return {
        "engines": engines,
        "get_vocabulary": get_vocabulary,
        "save_transcript": save_transcript,
        "save_job": save_job,
        "schedule": schedule,
        "saved_transcripts": saved_transcripts,
        "saved_jobs": saved_jobs,
        "scheduled": scheduled,
    }


def test_starting_a_job_persists_it_as_queued_and_returns_without_waiting():
    deps = make_job_deps()
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    job = asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["engines"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
            created_at=fixed,
        )
    )

    assert job.job_id == "job-1"
    assert job.meeting_id == "meeting-1"
    assert job.status == TranscriptionJobStatus.QUEUED
    assert job.created_at == fixed
    assert job.engine_lineages == ["engine-a", "engine-b"]
    assert deps["saved_jobs"] == [job]
    assert len(deps["scheduled"]) == 1
    # The batch run itself has not happened yet — only scheduled.
    assert deps["saved_transcripts"] == []


def test_a_job_id_is_generated_when_none_is_supplied():
    deps = make_job_deps()

    job = asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["engines"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
        )
    )

    assert job.job_id
    assert job.status == TranscriptionJobStatus.QUEUED


def test_running_the_scheduled_work_completes_the_job_and_saves_one_transcript_per_engine():
    deps = make_job_deps()

    job = asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["engines"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
        )
    )

    asyncio.run(deps["scheduled"][0]())

    assert len(deps["saved_transcripts"]) == 2
    assert all(t.session_id == "meeting-1" for t in deps["saved_transcripts"])
    assert all(
        t.status == TranscriptionStatus.COMPLETE for t in deps["saved_transcripts"]
    )
    assert deps["saved_jobs"][-1].job_id == job.job_id
    assert deps["saved_jobs"][-1].status == TranscriptionJobStatus.COMPLETE
    assert deps["saved_jobs"][-1].engine_lineages == ["engine-a", "engine-b"]


def test_the_job_completes_when_only_one_of_the_two_engines_succeeds():
    deps = make_job_deps(fail_a=True)

    asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["engines"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
        )
    )

    asyncio.run(deps["scheduled"][0]())

    statuses = {t.engine: t.status for t in deps["saved_transcripts"]}
    assert statuses["engine-a"] == TranscriptionStatus.FAILED
    assert statuses["engine-b"] == TranscriptionStatus.COMPLETE
    assert deps["saved_jobs"][-1].status == TranscriptionJobStatus.COMPLETE


def test_the_job_fails_only_when_both_engines_fail():
    deps = make_job_deps(fail_a=True, fail_b=True)

    asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["engines"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
        )
    )

    # Should not raise even though both batch engines failed.
    asyncio.run(deps["scheduled"][0]())

    assert deps["saved_jobs"][-1].status == TranscriptionJobStatus.FAILED
    assert all(
        t.status == TranscriptionStatus.FAILED for t in deps["saved_transcripts"]
    )
