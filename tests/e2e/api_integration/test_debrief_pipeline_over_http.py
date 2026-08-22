"""The §7 debrief pipeline, started by the thing that actually starts it.

`test_orchestration.py` drives `run_debrief_pipeline` directly and proves the
stage order. What it cannot see is whether anything in the running service ever
calls it: the pipeline is triggered from `save_transcript`, once every
record-path engine has finished, and that path only exists in the composition
root. A pipeline nobody starts and a pipeline that fails look identical from
the outside — both leave a meeting with no artifacts.

The inference seams are faked, as everywhere else in this suite. The trigger,
the fan-in over two engines, and the citations bound to filled coverage slots
are real.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    DiarizationOutput,
    SpeakerTurn,
    TemplateSection,
    TranslationOutcome,
)
from app.orchestration.engines import DebriefEngines
from conftest import configured_settings_store, fake_microsoft

SECTION = TemplateSection(key="performance", title="Performance")


def _working_engines() -> DebriefEngines:
    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        return DiarizationOutput(
            engine="fake",
            turns=[SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="client")],
        )

    async def clean(session_id: str, utterances: list) -> list[str]:
        return [u.text for u in utterances]

    async def translate(session_id: str, utterances: list, language: str) -> list:
        return [
            TranslationOutcome(original_language="en", translated_text=None)
            for _ in utterances
        ]

    async def classify(session_id: str, utterances: list, sections: list) -> list[str]:
        # Every utterance lands in the one configured section, so the matrix
        # has a filled slot for the citation binding to work on.
        return [SECTION.key for _ in utterances]

    async def run_chain(session_id: str, utterances: list) -> BmadAnalystChainOutput:
        # Every claim cites the utterances it came from: FR-8.7 is what stops
        # the chain asserting things the transcript does not support.
        ids = [u.utterance_id for u in utterances]
        return BmadAnalystChainOutput(
            open_questions=[
                BmadOpenQuestionDraft(
                    text="What is the dwell-time target?",
                    impact_rank=1,
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            decisions=[
                BmadDecisionDraft(
                    text="Rebuild depot scheduling",
                    decided_by="client",
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            project_brief=BmadProjectBriefDraft(
                body="Depot scheduling rebuild.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
            follow_up_email=BmadFollowUpEmailDraft(
                subject="Depot scheduling",
                body="Thanks for your time.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
        )

    return DebriefEngines(
        name="fake",
        diarize=diarize,
        clean=clean,
        translate=translate,
        classify=classify,
        run_chain=run_chain,
        converse=DebriefEngines.unconfigured().converse,
    )


@pytest.fixture
def backend() -> Backend:
    # The template the meeting is being run against. Configuration the app is
    # built with, not a read this test is standing in for.
    return Backend(template_sections=[SECTION])


@pytest.fixture
def client(backend: Backend) -> TestClient:
    return TestClient(
        build_app(
            backend,
            debrief_engines=_working_engines(),
            settings_store=configured_settings_store(),
            document_transport=fake_microsoft,
        )
    )


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Contoso Depots",
            "sector": "logistics",
            "commercial_context": "Scoping a depot scheduling rebuild",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "line-in"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def test_finishing_the_record_path_runs_the_debrief_and_produces_artifacts(
    client: TestClient, backend: Backend
) -> None:
    """The whole reason the record path exists: everything downstream derives from it."""

    meeting_id = _meeting(client)

    transcribed = client.post(
        f"/api/sessions/{meeting_id}/record-path-transcript",
        json={"audio_ref": "s3://retained/session.wav"},
    )
    assert transcribed.status_code == 201, transcribed.text
    # FR-2.6: two engines, so one finishing is not the session finishing.
    assert len(transcribed.json()) == 2

    run = backend.debrief_runs[meeting_id]
    assert run.complete, f"the pipeline stopped at {run.stopped_at}"
    assert "coverage-matrix" in run.stages_completed

    artifacts = client.get(f"/api/meetings/{meeting_id}/artifacts")
    assert artifacts.status_code == 200, artifacts.text
    assert artifacts.json(), "the run produced nothing addressable"


def test_a_filled_coverage_slot_carries_a_citation_into_the_matrix(
    client: TestClient, backend: Backend
) -> None:
    """A covered section is a claim, and a claim needs the utterance behind it.

    Without the citation the matrix says a section was covered and cannot say
    by what — which is the same as saying nothing.
    """

    meeting_id = _meeting(client)
    client.post(
        f"/api/sessions/{meeting_id}/record-path-transcript",
        json={"audio_ref": "s3://retained/session.wav"},
    )

    (matrix,) = backend.coverage_matrices[meeting_id]
    filled = [entry for entry in matrix.entries if entry.citations]

    assert filled, "no slot was filled, so nothing was cited"
    citation = filled[0].citations[0]
    # FR-2.7: the record path's wording, from a named engine, at a real span —
    # never the live path's interim guess.
    assert citation.session_id == meeting_id
    assert citation.engine in {"engine-a", "engine-b"}
    assert citation.quoted_text == "hello there"
    assert citation.end_seconds >= citation.start_seconds
    assert citation.transcript_completed_at is not None


def test_the_pipeline_is_not_started_twice_for_one_session(
    client: TestClient, backend: Backend
) -> None:
    # Re-running the analyst pass would duplicate every artifact and re-spend
    # the batch.
    meeting_id = _meeting(client)
    for _ in range(2):
        client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "s3://retained/session.wav"},
        )

    assert len(backend.coverage_matrices[meeting_id]) == 1
