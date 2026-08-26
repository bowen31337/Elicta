"""Asking for the write-up, for a meeting that has one owed.

The pipeline runs itself once, when the second record-path engine finishes,
and there is no other way to reach it — `/debrief/start` opens the
conversation rather than producing the artifacts. So a meeting whose run was
lost, or whose engines were misconfigured at the time, has transcripts, has
nothing to show, and has nothing to press.

That is the state the reported one was in: two complete transcripts, no
chain, and a screen saying a write-up "runs on its own once the recording has
been transcribed" — which had already happened.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.composition import Backend

_NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def _transcribed(backend: Backend, session_id: str) -> None:
    """A session whose record path finished, as the store would hold it."""

    # `asr-record` is hyphenated, so it is only reachable this way — the
    # status enum lives there with the transcript it belongs to.
    import importlib

    _models = importlib.import_module("app.modules.asr-record.models")
    backend.record_path_transcripts[session_id] = [
        _models.RecordPathTranscript(
            session_id=session_id,
            engine=engine,
            status=_models.TranscriptionStatus.COMPLETE,
            segments=[
                _models.TranscriptSegment(
                    start_seconds=0, end_seconds=4, text="We move many pallets a day.", speaker="client"
                )
            ],
            text="We move many pallets a day.",
            requested_at=_NOW,
            completed_at=_NOW,
        )
        for engine in ("deepgram", "assemblyai")
    ]


def test_the_write_up_can_be_asked_for(client: TestClient, backend: Backend) -> None:
    _transcribed(backend, "meeting-1")

    asked = client.post("/api/meetings/meeting-1/debrief/run")

    assert asked.status_code in (200, 202), asked.text


def test_a_meeting_with_nothing_transcribed_is_refused_rather_than_run(
    client: TestClient,
) -> None:
    """Running the pipeline over no transcript produces an empty write-up,
    which reads as a meeting where nothing was said."""

    refused = client.post("/api/meetings/nothing-here/debrief/run")

    assert refused.status_code == 409, refused.text
    assert "transcri" in refused.json()["detail"].lower()
