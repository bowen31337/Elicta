"""When a live session stops being live.

Reported from a running app: two sessions listed on one meeting, the first
open since half an hour before the second started. It was not a failure to
close — nothing closes one. `backend.live_sessions` had three references in
the whole service: the declaration, the write on start, and the read for the
listing. Every session a process ever started stayed in it.

`/api/sessions/live` answers "which meeting is being recorded", and it grew
by one row per recording for the life of the process. `receiving_audio` goes
false on its own, which hid how bad this was: the rows looked harmless
rather than wrong.
"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.trigger.listener import WINDOW_BYTES

PCM = base64.b64encode(b"\x00\x01" * (WINDOW_BYTES // 2)).decode()


def _client() -> TestClient:
    return TestClient(build_app(Backend()))


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "logistics",
            "commercial_context": "Discovery",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _live(client: TestClient) -> list[dict]:
    return client.get("/api/sessions/live").json()["sessions"]


class TestOneMeetingHasOneLiveSession:
    def test_starting_a_second_ends_the_first(self):
        """The reported shape exactly: record, stop, record again."""

        client = _client()
        meeting_id = _meeting(client)

        first = client.post(f"/api/meetings/{meeting_id}/session/start").json()
        second = client.post(f"/api/meetings/{meeting_id}/session/start").json()

        listed = _live(client)
        assert [s["session_id"] for s in listed] == [second["session_id"]]
        assert first["session_id"] != second["session_id"]

    def test_another_meeting_is_untouched(self):
        """Ending is per meeting. Two meetings can be recorded at once."""

        client = _client()
        one, two = _meeting(client), _meeting(client)

        client.post(f"/api/meetings/{one}/session/start")
        client.post(f"/api/meetings/{two}/session/start")

        assert {s["meeting_id"] for s in _live(client)} == {one, two}


class TestHandingOverTheAudioEndsIt:
    def test_starting_the_record_path_ends_the_session(self):
        """Which is what the desktop posts when the operator presses Stop.

        There is no other end-of-meeting signal: the app has no "end session"
        call, so without this a meeting that is stopped and not restarted
        stays listed as live until the process does.
        """

        client = _client()
        meeting_id = _meeting(client)
        client.post(f"/api/meetings/{meeting_id}/session/start")
        client.post(f"/api/sessions/{meeting_id}/recording", json={})
        client.post(f"/api/sessions/{meeting_id}/audio-chunk", json={"sequence": 0, "pcm": PCM})

        started = client.post(
            f"/api/meetings/{meeting_id}/record/transcribe",
            json={"audio_ref": f"session:{meeting_id}"},
        )

        assert started.status_code == 202, started.text
        assert _live(client) == []
