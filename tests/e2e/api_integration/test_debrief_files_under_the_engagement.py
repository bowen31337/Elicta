"""A write-up's requirements state belongs to the engagement, not the meeting.

The Engagement arc reads `/api/engagements/{id}/state`, and on a real
engagement it came back with `requirements_state: null` after a write-up that
had plainly succeeded — nine stages, a project brief, six decisions, eight
open questions. The state was there. It was filed under `meeting-3`.

`_run_debrief_when_record_path_completes` resolved the engagement with its own
inline chain ending `or session_id`, and the two maps before that fallback are
in-memory: after a restart neither knows anything about a meeting the previous
process created. So the fallback fired, and the state was filed under the
meeting id, where the arc — and the next meeting in the same engagement, which
is what FR-3.11 carries forward — can never find it.

The durable answer was already available and already used elsewhere.
`_engagement_of_meeting` consults the in-memory map *and* the meeting's own
row, and its docstring explains precisely this hazard. This call site simply
did not reach for it.
"""

from __future__ import annotations

import contextlib
import importlib
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


def _engines() -> DebriefEngines:
    async def stop(*_args, **_kwargs):
        raise RuntimeError("stopped past the point under test")

    return DebriefEngines(
        name="stub", diarize=stop, clean=stop, translate=stop,
        classify=stop, run_chain=stop, converse=stop,
    )


def _transcript(meeting_id: str, engine: str):
    now = datetime.now(UTC)
    return _asr.RecordPathTranscript(
        session_id=meeting_id,
        engine=engine,
        status=_asr.TranscriptionStatus.COMPLETE,
        text="we onboard a lot of joiners",
        segments=[
            _asr.TranscriptSegment(
                start_seconds=0.0, end_seconds=1.0,
                text="we onboard a lot of joiners", speaker="a",
            )
        ],
        requested_at=now,
        completed_at=now,
    )


def test_the_engagement_is_resolved_from_the_meetings_own_row(tmp_path):
    """Which is the only record of it that survives a restart."""

    from app.composition import _engagement_of_meeting

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, backend):
        engagement = client.post(
            "/api/engagements",
            json={"client_organisation": "Arc", "sector": "s", "commercial_context": "c"},
        )
        engagement_id = engagement.json()["engagement_id"]
        meeting = client.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "microphone"},
        )
        meeting_id = meeting.json()["meeting_id"]

        # The state a restart leaves: the in-memory map is gone, the row is not.
        backend.meeting_engagement_ids.clear()
        backend.session_engagement_ids.clear()

        assert _engagement_of_meeting(backend, meeting_id) == engagement_id


def test_a_write_up_after_a_restart_still_files_under_the_engagement(tmp_path):
    """The arc asks for the engagement, so that is where it has to be."""

    url = f"sqlite:///{tmp_path / 'state.db'}"
    with _client(url, _engines()) as (client, backend):
        engagement = client.post(
            "/api/engagements",
            json={"client_organisation": "Arc", "sector": "s", "commercial_context": "c"},
        )
        engagement_id = engagement.json()["engagement_id"]
        meeting_id = client.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "microphone"},
        ).json()["meeting_id"]
        backend.record_path_transcripts[meeting_id] = [
            _transcript(meeting_id, "deepgram"),
            _transcript(meeting_id, "assemblyai"),
        ]

        # A restart between the meeting being created and the write-up being
        # asked for, which is the ordinary case: the button exists precisely
        # for a run that did not happen when the recording finished.
        backend.meeting_engagement_ids.clear()
        backend.session_engagement_ids.clear()

        seen: dict = {}
        import app.composition as composition

        original = composition.run_debrief_pipeline

        async def capture(session_id, **kwargs):
            seen["engagement_id"] = kwargs.get("engagement_id")
            return await original(session_id, **kwargs)

        composition.run_debrief_pipeline = capture
        try:
            client.post(f"/api/meetings/{meeting_id}/debrief/run")
            for _ in range(60):
                if not client.get(
                    f"/api/meetings/{meeting_id}/debrief/completion"
                ).json()["running"]:
                    break
                import time

                time.sleep(0.05)
        finally:
            composition.run_debrief_pipeline = original

    assert seen.get("engagement_id") == engagement_id, (
        f"filed under {seen.get('engagement_id')!r} — the arc asks for "
        f"{engagement_id!r} and finds nothing there"
    )
