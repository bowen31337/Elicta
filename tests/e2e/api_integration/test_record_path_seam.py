"""A transcribed recording produces divergences that can be read back.

The defect this covers: `POST /record/transcribe` returned a queued job with
two engine lineages and `GET /record/divergences` answered "record-path
alignment not found", because the composition root's `schedule` was a no-op
whose own docstring said "never actually run the scheduled work ... tests for
what a completed job leaves behind seed `backend` directly". A job accepted
and never run is a job that reports QUEUED forever.

This is the seam, not the vendor: both record-path engines here are the
composition root's stand-ins, so nothing leaves the machine. What is being
proved is that transcribing a meeting produces an alignment the divergences
route can read.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _meeting(client: TestClient) -> str:
    engagement = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Ridgeway Health",
            "sector": "healthcare",
            "commercial_context": "Discovery for a referrals rebuild",
        },
    )
    assert engagement.status_code == 201, engagement.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": engagement.json()["engagement_id"], "capture_mode": "record"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _divergences_once_run(client: TestClient, meeting_id: str, timeout: float = 5.0):
    """Poll the divergences route while the accepted job runs.

    The transcribe endpoint answers 202 and the batch run continues after the
    response, so the read is polled rather than assumed instant — that is what
    a job handle means. It is bounded, so a run that never happens fails the
    test rather than hanging it.
    """

    deadline = time.monotonic() + timeout
    response = client.get(f"/api/meetings/{meeting_id}/record/divergences")
    while response.status_code == 404 and time.monotonic() < deadline:
        time.sleep(0.02)
        response = client.get(f"/api/meetings/{meeting_id}/record/divergences")
    return response


def test_transcribing_a_meeting_produces_readable_divergences(client: TestClient) -> None:
    meeting_id = _meeting(client)

    started = client.post(
        f"/api/meetings/{meeting_id}/record/transcribe",
        json={"audio_ref": "s3://recordings/ridgeway-01.wav"},
    )
    assert started.status_code == 202, started.text
    assert started.json()["engine_lineages"] == ["engine-a", "engine-b"]

    response = _divergences_once_run(client, meeting_id)

    assert response.status_code == 200, response.text
    alignment = response.json()
    assert alignment["session_id"] == meeting_id
    assert {alignment["reference_engine"], alignment["other_engine"]} == {
        "engine-a",
        "engine-b",
    }


def test_two_engines_that_agree_produce_an_empty_divergence_list(
    client: TestClient,
) -> None:
    """No divergence is an answer, not an error — FR-2.8 surfaces what differs."""

    meeting_id = _meeting(client)
    client.post(
        f"/api/meetings/{meeting_id}/record/transcribe",
        json={"audio_ref": "s3://recordings/ridgeway-01.wav"},
    )

    response = _divergences_once_run(client, meeting_id)

    assert response.status_code == 200, response.text
    assert response.json()["spans"] == []


def test_a_meeting_that_was_never_transcribed_has_no_alignment(
    client: TestClient,
) -> None:
    meeting_id = _meeting(client)

    response = client.get(f"/api/meetings/{meeting_id}/record/divergences")

    assert response.status_code == 404


def test_a_session_whose_audio_was_never_destroyed_says_so(client: TestClient) -> None:
    """NFR-2.4 asks the discard to be observable, not merely to happen.

    A 404 means no attempt has been made, which is deliberately distinct from
    a `FAILED` event — that one means the audio may still be sitting there and
    somebody needs to know. The positive case needs a debrief pipeline to have
    diarized the session, so it lives in `test_debrief_artifacts_seam.py`,
    where an engine is substituted; there is no honest way to reach it here.
    """

    meeting_id = _meeting(client)

    assert client.get(f"/api/sessions/{meeting_id}/audio-destruction").status_code == 404
