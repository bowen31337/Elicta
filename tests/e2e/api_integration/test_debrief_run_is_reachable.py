"""Asking for a write-up, and being told what became of it.

Three defects, found from a meeting with eight completed transcripts, no
artifacts, and nothing on screen to explain either.

`POST /debrief/run` declares 202 and then awaits the whole pipeline --
diarize, clean, translate, classify and the analyst chain, every one a model
call over a transcript of a couple of hundred segments. The operator presses
the button and the request hangs for minutes with the screen saying
"Writing it up...", which is indistinguishable from a button that does
nothing, and any client or proxy timeout in between turns it into one.

What the run recorded lived in a plain dict. A restart erased it, so a
pipeline that stopped at a stage left no trace at all: the screen went back
to "no write-up has been produced yet", which is the one thing that was not
true. The artifacts survive -- `bmad_chains` is durable -- so this is only
ever the explanation that goes missing, which is exactly when an operator
needs one.

And the reference transcript was the *first* completed one. A meeting
recorded four times, read back after a restart with no hold to mark where
the last recording began, drafts its documents from the first attempt.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.orchestration.engines import DebriefEngines


@contextlib.contextmanager
def _client(url: str, engines: DebriefEngines):
    from app.composition import attach_state_store
    from app.persistence.store import open_state_store

    store = open_state_store(url)
    backend = attach_state_store(Backend(), store)
    with TestClient(build_app(backend, debrief_engines=engines)) as client:
        yield client, backend
    store.close()


def _engines(*, seconds: float = 0.0, fail: str = "stopped in a stub") -> DebriefEngines:
    async def stage(*_args, **_kwargs):
        if seconds:
            await asyncio.sleep(seconds)
        raise RuntimeError(fail)

    return DebriefEngines(
        name="stub",
        diarize=stage,
        clean=stage,
        translate=stage,
        classify=stage,
        run_chain=stage,
        converse=stage,
    )


def _meeting_with_transcripts(client: TestClient, backend: Backend, count: int = 2) -> str:
    """A meeting whose record path has finished, as the pipeline needs it."""

    engagement = client.post(
        "/api/engagements",
        json={"client_organisation": "Debrief", "sector": "s", "commercial_context": "c"},
    )
    meeting = client.post(
        "/api/meetings",
        json={
            "engagement_id": engagement.json()["engagement_id"],
            "capture_mode": "microphone",
        },
    )
    meeting_id = meeting.json()["meeting_id"]
    backend.record_path_transcripts[meeting_id] = _transcripts(meeting_id, count)
    return meeting_id


def _transcripts(meeting_id: str, recordings: int):
    """`recordings` pairs of completed transcripts, oldest first."""

    made = []
    for take in range(recordings):
        for engine in ("deepgram", "assemblyai"):
            made.append(_transcript(meeting_id, engine, take))
    return made


def _transcript(meeting_id: str, engine: str, take: int):
    # The module dir is hyphenated, so a literal import of it is a syntax
    # error; `composition` reaches it the same way.
    import importlib
    from datetime import datetime, timezone

    models = importlib.import_module("app.modules.asr-record.models")
    now = datetime.now(timezone.utc)
    return models.RecordPathTranscript(
        session_id=meeting_id,
        engine=engine,
        status=models.TranscriptionStatus.COMPLETE,
        text=f"take {take} heard by {engine}",
        segments=[
            models.TranscriptSegment(
                start_seconds=0.0, end_seconds=1.0, text=f"take {take} heard by {engine}"
            )
        ],
        requested_at=now,
        completed_at=now,
    )


def test_the_request_comes_back_before_the_pipeline_does(tmp_path):
    """A 202 that waits for the work is not a 202."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(seconds=3.0)) as (client, backend):
        meeting_id = _meeting_with_transcripts(client, backend)

        began = time.time()
        response = client.post(f"/api/meetings/{meeting_id}/debrief/run")
        took = time.time() - began

        assert response.status_code == 202, response.text
        assert took < 1.5, (
            f"the caller was held for {took:.1f}s of a 3s pipeline — with real "
            "engines that is minutes of a screen that looks stuck"
        )


def test_the_screen_can_say_a_write_up_is_under_way(tmp_path):
    """Otherwise pressing the button changes nothing an operator can see."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(seconds=3.0)) as (client, backend):
        meeting_id = _meeting_with_transcripts(client, backend)
        client.post(f"/api/meetings/{meeting_id}/debrief/run")

        completion = client.get(f"/api/meetings/{meeting_id}/debrief/completion")
        assert completion.status_code == 200, (
            "a run that has been asked for is not the same as one never asked for"
        )
        assert completion.json()["running"] is True


def test_what_stopped_a_run_is_still_there_after_a_restart(tmp_path):
    """The explanation is the one thing that used to go missing."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines(fail="the diarizer is not configured")) as (client, backend):
        meeting_id = _meeting_with_transcripts(client, backend)
        client.post(f"/api/meetings/{meeting_id}/debrief/run")
        for _ in range(50):
            body = client.get(f"/api/meetings/{meeting_id}/debrief/completion").json()
            if not body["running"]:
                break
            time.sleep(0.05)
        assert body["stopped_at"] == "diarization"

    with _client(url, _engines()) as (client, _backend):
        after = client.get(f"/api/meetings/{meeting_id}/debrief/completion")

    assert after.status_code == 200, "a restart erased the only record of what happened"
    assert after.json()["stopped_at"] == "diarization"
    assert after.json()["running"] is False


def test_the_write_up_is_drafted_from_the_latest_recording(tmp_path):
    """A meeting recorded four times is written up from the fourth.

    Asserted on `current_recording_transcripts`, which is where the choice is
    made: the pipeline drafts from the first COMPLETE transcript in whatever
    it is handed, so handing it the whole history hands it the first attempt.

    The hold carries the baseline that separates one recording from the next,
    and the hold is in memory — so after a restart there is no baseline, and
    after a restart is when the operator presses the button.
    """

    from app.composition import current_recording_transcripts

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, backend):
        meeting_id = _meeting_with_transcripts(client, backend, count=4)
        assert backend.session_audio.get(meeting_id) is None, (
            "no hold — the state this test is about"
        )

        current = current_recording_transcripts(backend, meeting_id)

    assert len(current) == backend.record_path_engine_count
    assert [t.text for t in current] == [
        "take 3 heard by deepgram",
        "take 3 heard by assemblyai",
    ]
