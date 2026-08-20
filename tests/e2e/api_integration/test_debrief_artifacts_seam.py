"""A debrief produces artifacts the meeting can list.

The defect this covers: `backend.meeting_artifacts` and
`backend.artifacts_by_id` were read by the artifact list and detail routes and
written by nothing, and `backend.bmad_chains` — which the project brief,
decision log, open questions and follow-up email routes all read — was the
read-only twin of `backend.analyst_chains`, which the pipeline wrote and
nobody read. So a debrief ran, produced its artifact set, and every one of the
six routes that should show it answered 404 or an empty list.

The five inference seams are faked so the test does not need a model; the
meeting, its recording and its debrief all happen through the API.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from app.composition import Backend, build_app
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    DiarizationOutput,
    SpeakerTurn,
    TranslationOutcome,
)
from app.orchestration.engines import DebriefEngines
from fastapi.testclient import TestClient


@pytest.fixture
def debriefing_client() -> TestClient:
    """An app whose five debrief seams answer, so the §7 pipeline can complete."""

    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        return DiarizationOutput(
            engine="fake",
            turns=[SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="client")],
        )

    async def clean(session_id: str, utterances: list[Any]) -> list[str]:
        return [u.text for u in utterances]

    async def translate(
        session_id: str, utterances: list[Any], language: str
    ) -> list[TranslationOutcome]:
        return [
            TranslationOutcome(original_language="en", translated_text=None)
            for _ in utterances
        ]

    async def classify(
        session_id: str, utterances: list[Any], sections: list[Any]
    ) -> list[str]:
        return ["performance" for _ in utterances]

    async def run_chain(session_id: str, utterances: list[Any]) -> BmadAnalystChainOutput:
        ids = [u.utterance_id for u in utterances]
        return BmadAnalystChainOutput(
            open_questions=[
                BmadOpenQuestionDraft(
                    text="What does 'fast' mean in seconds?",
                    impact_rank=1,
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            decisions=[
                BmadDecisionDraft(
                    text="Ship the referrals API first",
                    decided_by="client",
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            project_brief=BmadProjectBriefDraft(
                body="A referrals discovery engagement.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
            follow_up_email=BmadFollowUpEmailDraft(
                subject="Follow-ups from today",
                body="Thanks — two open points.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
        )

    unconfigured = DebriefEngines.unconfigured()
    engines = DebriefEngines(
        name="fake",
        diarize=diarize,
        clean=clean,
        translate=translate,
        classify=classify,
        run_chain=run_chain,
        converse=unconfigured.converse,
    )
    return TestClient(build_app(Backend(), debrief_engines=engines))


def _debriefed_meeting(client: TestClient, timeout: float = 5.0) -> str:
    """A meeting whose recording has been transcribed and debriefed, over the API."""

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
    meeting_id = meeting.json()["meeting_id"]

    started = client.post(
        f"/api/meetings/{meeting_id}/record/transcribe",
        json={"audio_ref": "s3://recordings/ridgeway-01.wav"},
    )
    assert started.status_code == 202, started.text

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/api/meetings/{meeting_id}/artifacts").json():
            break
        time.sleep(0.02)
    return meeting_id


def test_the_four_debrief_artifacts_can_each_be_read(debriefing_client: TestClient) -> None:
    meeting_id = _debriefed_meeting(debriefing_client)

    brief = debriefing_client.get(f"/api/sessions/{meeting_id}/project-brief")
    assert brief.status_code == 200, brief.text
    assert brief.json()["body"] == "A referrals discovery engagement."

    decisions = debriefing_client.get(f"/api/sessions/{meeting_id}/decision-log")
    assert decisions.status_code == 200, decisions.text
    assert decisions.json()[0]["text"] == "Ship the referrals API first"

    questions = debriefing_client.get(f"/api/sessions/{meeting_id}/open-questions")
    assert questions.status_code == 200, questions.text
    assert questions.json()[0]["text"] == "What does 'fast' mean in seconds?"

    email = debriefing_client.get(f"/api/sessions/{meeting_id}/follow-up-email")
    assert email.status_code == 200, email.text
    assert email.json()["subject"] == "Follow-ups from today"


def test_the_meeting_lists_the_artifacts_the_debrief_produced(
    debriefing_client: TestClient,
) -> None:
    meeting_id = _debriefed_meeting(debriefing_client)

    response = debriefing_client.get(f"/api/meetings/{meeting_id}/artifacts")

    assert response.status_code == 200, response.text
    listed = response.json()
    assert listed, "the debrief produced no artifacts to list"
    kinds = {artifact["artifact_type"] for artifact in listed}
    assert {"project_brief", "decision_log", "open_questions", "follow_up_email"} <= kinds


def test_every_listed_artifact_resolves_by_its_own_id(
    debriefing_client: TestClient,
) -> None:
    meeting_id = _debriefed_meeting(debriefing_client)
    listed = debriefing_client.get(f"/api/meetings/{meeting_id}/artifacts").json()

    for summary in listed:
        detail = debriefing_client.get(f"/api/artifacts/{summary['artifact_id']}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["artifact_type"] == summary["artifact_type"]
        assert body["session_id"] == meeting_id
        assert body["body"], f"{summary['artifact_type']} resolved to an empty body"


def test_a_meeting_with_no_debrief_lists_nothing_and_404s_its_artifacts(
    client: TestClient,
) -> None:
    """The empty case stays empty — and stays distinguishable from a real one."""

    assert client.get("/api/meetings/meeting-1/artifacts").json() == []
    assert client.get("/api/sessions/meeting-1/project-brief").status_code == 404
    assert client.get("/api/artifacts/artifact-1").status_code == 404


def test_the_audio_destruction_is_readable_once_the_debrief_has_run(
    debriefing_client: TestClient,
) -> None:
    """NFR-2.4 requires the discard to be observable, not merely to happen.

    The event was persisted whether the deletion succeeded or failed, and
    served back nowhere — so the recording screen, whose job is to tell a
    reviewer what became of the audio, had nothing to read. Destruction is
    gated on both record-path transcription and diarization finishing, which
    is why this belongs to the debrief fixture rather than the record-path one.
    """

    meeting_id = _debriefed_meeting(debriefing_client)

    response = debriefing_client.get(f"/api/sessions/{meeting_id}/audio-destruction")

    assert response.status_code == 200, response.text
    event = response.json()
    assert event["session_id"] == meeting_id
    assert event["status"] == "complete"
    assert event["audio_ref"] == "s3://recordings/ridgeway-01.wav"
    assert event["completed_at"]


def test_open_questions_carry_forward_onto_the_engagement(
    debriefing_client: TestClient,
) -> None:
    """FR-3.11: what one meeting leaves unanswered is what the next is for.

    `engagement_open_questions` is what `GET /api/engagements/{id}/state`
    reads, and only rehydration from the durable store ever filled it — so a
    debrief could raise five open questions and the engagement carried none of
    them into the next meeting.
    """

    engagement = debriefing_client.post(
        "/api/engagements",
        json={
            "client_organisation": "Ridgeway Health",
            "sector": "healthcare",
            "commercial_context": "Discovery for a referrals rebuild",
        },
    )
    assert engagement.status_code == 201, engagement.text
    engagement_id = engagement.json()["engagement_id"]

    meeting = debriefing_client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "record"},
    )
    assert meeting.status_code == 201, meeting.text
    meeting_id = meeting.json()["meeting_id"]

    started = debriefing_client.post(
        f"/api/meetings/{meeting_id}/record/transcribe",
        json={"audio_ref": "s3://recordings/ridgeway-03.wav"},
    )
    assert started.status_code == 202, started.text

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if debriefing_client.get(f"/api/meetings/{meeting_id}/artifacts").json():
            break
        time.sleep(0.02)

    response = debriefing_client.get(f"/api/engagements/{engagement_id}/state")

    assert response.status_code == 200, response.text
    carried = response.json()["inherited_open_questions"]
    assert [question["text"] for question in carried] == [
        "What does 'fast' mean in seconds?"
    ]
