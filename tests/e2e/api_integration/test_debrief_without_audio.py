"""Writing up a meeting whose audio is gone, which is every meeting eventually.

Architecture §7.2 diarizes the retained audio; §7.3 destroys it (NFR-2.4).
That ordering works exactly once -- on the run that fires the moment the
second record-path engine finishes. Every later run has no audio, and a later
run is precisely what "Write it up now" is for: a meeting whose first attempt
was lost to a restart, or whose engines were misconfigured at the time.

Observed on a real meeting: eight completed transcripts, no artifacts, and a
stored outcome of `no audio held for meeting-3: nothing to transcribe`.

The answer was already in the transcript. Both record-path engines diarize as
part of transcribing -- that meeting's segments carry seven distinct speaker
tags from each -- so a second pass over audio that no longer exists is asking
for work that has been done. The tags are used when the audio is gone, and
only then: with audio in hand the dedicated pass is better, because it hears
the whole session rather than one engine's segmentation of it.

And when there is neither, the operator is told what is actually missing.
Falling through to "failed" put "The call it needed did not get through" on
screen -- a network diagnosis, invented, for a run that made no call.
"""

from __future__ import annotations

import contextlib
import importlib
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import DebriefEngines

_asr = importlib.import_module("app.modules.asr-record.models")


@contextlib.contextmanager
def _client(url: str, engines: DebriefEngines):
    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend, debrief_engines=engines)) as client:
        yield client, backend
    store.close()


def _engines(diarize=None) -> DebriefEngines:
    """Stops after diarization, so the test reads that stage's outcome."""

    async def refuse(*_args, **_kwargs):
        raise RuntimeError("stopped past the stage under test")

    async def no_audio(*_args, **_kwargs):
        raise RuntimeError("no audio held for this session: nothing to transcribe")

    return DebriefEngines(
        name="stub",
        diarize=diarize or no_audio,
        clean=refuse,
        translate=refuse,
        classify=refuse,
        run_chain=refuse,
        converse=refuse,
    )


def _transcript(meeting_id: str, engine: str, *, speakers: bool):
    now = datetime.now(UTC)
    tags = ["a", "b"] if speakers else [None, None]
    return _asr.RecordPathTranscript(
        session_id=meeting_id,
        engine=engine,
        status=_asr.TranscriptionStatus.COMPLETE,
        text="we onboard a lot of joiners. how many is a lot?",
        segments=[
            _asr.TranscriptSegment(
                start_seconds=0.0, end_seconds=2.0,
                text="we onboard a lot of joiners", speaker=tags[0],
            ),
            _asr.TranscriptSegment(
                start_seconds=2.0, end_seconds=4.0,
                text="how many is a lot?", speaker=tags[1],
            ),
        ],
        requested_at=now,
        completed_at=now,
    )


def _meeting(client: TestClient, backend: Backend, *, speakers: bool) -> str:
    engagement = client.post(
        "/api/engagements",
        json={"client_organisation": "NoAudio", "sector": "s", "commercial_context": "c"},
    )
    meeting = client.post(
        "/api/meetings",
        json={
            "engagement_id": engagement.json()["engagement_id"],
            "capture_mode": "microphone",
        },
    )
    meeting_id = meeting.json()["meeting_id"]
    backend.record_path_transcripts[meeting_id] = [
        _transcript(meeting_id, "deepgram", speakers=speakers),
        _transcript(meeting_id, "assemblyai", speakers=speakers),
    ]
    # No hold: the audio is gone, which is the state every meeting reaches.
    assert backend.session_audio.get(meeting_id) is None
    return meeting_id


def _settled(client: TestClient, meeting_id: str) -> dict:
    for _ in range(60):
        body = client.get(f"/api/meetings/{meeting_id}/debrief/completion").json()
        if not body["running"]:
            return body
        time.sleep(0.05)
    raise AssertionError("the run never finished")


def test_speaker_tags_already_in_the_transcript_carry_the_diarization(tmp_path):
    """A second pass over audio that no longer exists is work already done."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, backend):
        meeting_id = _meeting(client, backend, speakers=True)
        client.post(f"/api/meetings/{meeting_id}/debrief/run")
        body = _settled(client, meeting_id)

    assert "diarization" in body["stages_completed"], (
        f"diarization should have been satisfied from the transcript: {body}"
    )


def test_the_audio_engine_is_still_preferred_while_there_is_audio(tmp_path):
    """With audio in hand the dedicated pass hears the whole session."""

    reached = {}

    async def real_engine(session_id, audio_ref):
        reached["called"] = True
        raise RuntimeError("the engine was reached, which is the point")

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(diarize=real_engine)) as (client, backend):
        meeting_id = _meeting(client, backend, speakers=True)
        # Audio is held again, as it is on the run that fires automatically.
        backend.session_audio[meeting_id] = _Hold()
        client.post(f"/api/meetings/{meeting_id}/debrief/run")
        _settled(client, meeting_id)

    assert reached.get("called") is True, (
        "the transcript's tags must not displace a diarizer that can run"
    )


def test_no_audio_and_no_tags_says_what_is_actually_missing(tmp_path):
    """Never a network diagnosis for a run that made no call."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, backend):
        meeting_id = _meeting(client, backend, speakers=False)
        client.post(f"/api/meetings/{meeting_id}/debrief/run")
        body = _settled(client, meeting_id)

    assert body["stopped_at"] == "diarization"
    assert body["cause"] == "input_gone", (
        f"'failed' renders as 'the call did not get through', which is invented: {body}"
    )


class _Hold:
    """The shape `session_audio` holds, as far as the pipeline reads it."""

    epoch = 0
    transcript_baseline = 0
    buffer = b"\x00\x00"
