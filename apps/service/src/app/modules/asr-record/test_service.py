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
    text: str = "the full session transcript",
) -> BatchTranscriptionOutput:
    return BatchTranscriptionOutput(
        engine="highest-accuracy-engine",
        segments=[
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="the full"),
            TranscriptSegment(
                start_seconds=1.5, end_seconds=3.0, text="session transcript"
            ),
        ],
        text=text,
    )


def test_a_successful_run_persists_a_complete_transcript_for_the_full_session():
    saved: list[RecordPathTranscript] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        assert session_id == "session-1"
        assert audio_ref == "recordings/session-1.wav"
        return make_output()

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        return ["Acme Corp", "Project Nightingale"]

    result = asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", transcribe, save, get_vocabulary
        )
    )

    assert result.status == TranscriptionStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "highest-accuracy-engine"
    assert result.text == "the full session transcript"
    assert len(result.segments) == 2
    assert result.error is None
    assert saved == [result]


def test_the_engagement_vocabulary_is_sent_as_keyterms_on_every_batch_request():
    sent_keyterms: list[list[str]] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        sent_keyterms.append(keyterms)
        return make_output()

    async def save(transcript: RecordPathTranscript) -> None:
        pass

    async def get_vocabulary(session_id: str) -> list[str]:
        return ["Acme Corp", "Project Nightingale", "SSO"]

    asyncio.run(
        run_record_path_transcription(
            "session-1", "recordings/session-1.wav", transcribe, save, get_vocabulary
        )
    )

    assert sent_keyterms == [["Acme Corp", "Project Nightingale", "SSO"]]


def test_requested_at_is_deterministic_when_supplied():
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        return make_output()

    async def save(transcript: RecordPathTranscript) -> None:
        pass

    async def get_vocabulary(session_id: str) -> list[str]:
        return []

    result = asyncio.run(
        run_record_path_transcription(
            "session-1",
            "recordings/session-1.wav",
            transcribe,
            save,
            get_vocabulary,
            requested_at=fixed,
        )
    )

    assert result.requested_at == fixed
    assert result.completed_at >= fixed


def test_an_engine_failure_persists_a_failed_transcript_and_reraises():
    saved: list[RecordPathTranscript] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        raise RuntimeError("vendor engine timed out")

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        return []

    with pytest.raises(RuntimeError, match="vendor engine timed out"):
        asyncio.run(
            run_record_path_transcription(
                "session-1", "recordings/session-1.wav", transcribe, save, get_vocabulary
            )
        )

    assert len(saved) == 1
    assert saved[0].status == TranscriptionStatus.FAILED
    assert saved[0].session_id == "session-1"
    assert saved[0].error == "vendor engine timed out"
    assert saved[0].segments == []


def test_a_vocabulary_lookup_failure_also_persists_a_failed_transcript_and_reraises():
    saved: list[RecordPathTranscript] = []

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        raise AssertionError("transcribe should not run if vocabulary lookup fails")

    async def save(transcript: RecordPathTranscript) -> None:
        saved.append(transcript)

    async def get_vocabulary(session_id: str) -> list[str]:
        raise RuntimeError("engagement lookup unavailable")

    with pytest.raises(RuntimeError, match="engagement lookup unavailable"):
        asyncio.run(
            run_record_path_transcription(
                "session-1", "recordings/session-1.wav", transcribe, save, get_vocabulary
            )
        )

    assert len(saved) == 1
    assert saved[0].status == TranscriptionStatus.FAILED
    assert saved[0].error == "engagement lookup unavailable"


def make_job_deps(*, fail: bool = False):
    saved_transcripts: list[RecordPathTranscript] = []
    saved_jobs: list[RecordPathTranscriptionJob] = []
    scheduled: list = []

    async def transcribe(
        meeting_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        if fail:
            raise RuntimeError("vendor engine unavailable")
        return make_output()

    async def get_vocabulary(meeting_id: str) -> list[str]:
        return []

    async def save_transcript(transcript: RecordPathTranscript) -> None:
        saved_transcripts.append(transcript)

    async def save_job(job: RecordPathTranscriptionJob) -> None:
        saved_jobs.append(job)

    def schedule(work) -> None:
        scheduled.append(work)

    return {
        "transcribe": transcribe,
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
            deps["transcribe"],
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
            deps["transcribe"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
        )
    )

    assert job.job_id
    assert job.status == TranscriptionJobStatus.QUEUED


def test_running_the_scheduled_work_completes_the_job_and_saves_the_transcript():
    deps = make_job_deps()

    job = asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["transcribe"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
        )
    )

    asyncio.run(deps["scheduled"][0]())

    assert deps["saved_transcripts"][0].session_id == "meeting-1"
    assert deps["saved_transcripts"][0].status == TranscriptionStatus.COMPLETE
    assert deps["saved_jobs"][-1].job_id == job.job_id
    assert deps["saved_jobs"][-1].status == TranscriptionJobStatus.COMPLETE


def test_running_the_scheduled_work_marks_the_job_failed_without_raising():
    deps = make_job_deps(fail=True)

    asyncio.run(
        start_record_path_transcription_job(
            "meeting-1",
            "recordings/meeting-1.wav",
            deps["transcribe"],
            deps["get_vocabulary"],
            deps["save_transcript"],
            deps["save_job"],
            deps["schedule"],
            job_id="job-1",
        )
    )

    # Should not raise even though the batch engine failed.
    asyncio.run(deps["scheduled"][0]())

    assert deps["saved_jobs"][-1].status == TranscriptionJobStatus.FAILED
    assert deps["saved_transcripts"][-1].status == TranscriptionStatus.FAILED
