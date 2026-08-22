"""One meeting, start to finish, asserted rather than observed.

Every other suite here tests a seam. This drives the whole arc of a meeting
through the production composition root in one pass — prepare, record, review
the disagreements, destroy the audio, run the write-up, read the documents,
carry the state forward — and asserts what each step produced.

**Nothing here talks to a model, and that is the point.** The four seams with
no vendor behind them (two record-path engines, the diarizer, the live nudge
stream) are supplied from `tests/e2e/fixture_run`, and the five debrief stages
answer deterministically from the same recorded meeting. Everything between
them is the real pipeline: `run_debrief_pipeline`'s nine stages in order, the
real citation resolution, the real coverage matrix, the real forward merge.

The alternative — asserting against a live provider — was measured before this
existed: two runs in three came back rate limited, overloaded, or one entry
out, none of which says anything about whether the pipeline is correct. A
happy path that passes two times in three is not a happy path. The live run
still exists, in `tests/e2e/fixture_run/run.py`, for proving the same journey
against the real model; this is the one that must never flake.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.e2e.fixture_run import fixtures  # noqa: E402
from tests.e2e.fixture_run.fixture_engines import fixture_debrief_engines  # noqa: E402
from tests.e2e.fixture_run.harness import fixture_diarizer, record_path_engine  # noqa: E402

from app.composition import Backend, build_app  # noqa: E402
from app.modules.debrief.pipeline.models import TemplateSection  # noqa: E402

VOCABULARY = ["FROSTLINE", "NAVISTOCK", "Wolverhampton", "Derby", "marshalling"]


class Journey:
    """What one run of the whole meeting produced, for the assertions below."""

    def __init__(self, client: TestClient, engines: list[tuple[str, Any]]) -> None:
        self.client = client
        self.engines = engines
        self.engagement_id = ""
        self.meeting_id = ""

    def get(self, path: str) -> Any:
        response = self.client.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        return response.json()


@pytest.fixture(scope="module")
def journey() -> Any:
    """Drive the meeting once; every test below reads what it produced."""

    backend = Backend()
    # Nothing in the product writes these yet, and classification needs the
    # taxonomy it is scoring against (PRD D5 leaves the taxonomy to the caller).
    backend.template_sections = [
        TemplateSection(key=section.lower().replace(" ", "-"), title=section)
        for section in fixtures.TEMPLATE_SECTIONS
    ]

    engines = [
        record_path_engine("fixture-engine-a", mishear=False),
        record_path_engine("fixture-engine-b", mishear=True),
    ]
    app = build_app(
        backend,
        debrief_engines=fixture_debrief_engines(fixture_diarizer()),
        record_path_engines=engines,
    )

    with TestClient(app) as client:
        run = Journey(client, engines)

        created = client.post(
            "/api/engagements",
            json={
                "client_organisation": "Northgate Chilled Logistics",
                "sector": "Cold-chain distribution",
                "commercial_context": "Fixed-price discovery, three meetings",
            },
        )
        assert created.status_code == 201, created.text
        run.engagement_id = created.json()["engagement_id"]

        for name, body, status in (
            ("Northgate-Scoping-Brief.txt", b"FROSTLINE dates from 2011.", "hypothesis"),
            ("Northgate-Throughput-Study.txt", b"Wolverhampton averages 268 pallets.", "ground truth"),
        ):
            attached = client.post(
                f"/api/engagements/{run.engagement_id}/documents",
                files={"file": (name, body, "text/plain")},
                data={"status": status},
            )
            assert attached.status_code == 201, attached.text

        for term in VOCABULARY:
            added = client.post(
                f"/api/engagements/{run.engagement_id}/vocabulary",
                json={"term": term, "term_type": "internal_system"},
            )
            assert added.status_code == 201, added.text

        meeting = client.post(
            "/api/meetings",
            json={"engagement_id": run.engagement_id, "capture_mode": "record"},
        )
        assert meeting.status_code == 201, meeting.text
        run.meeting_id = meeting.json()["meeting_id"]

        # The live half. Scripted, and openly so: turning an utterance into a
        # surfaced nudge needs the trigger gate and the ranker, which are Rust
        # crates this process cannot reach.
        backend.session_stream_events[run.meeting_id] = list(fixtures.SESSION_SCRIPT)
        started = client.post(f"/api/meetings/{run.meeting_id}/session/start")
        assert started.status_code in (200, 201), started.text

        with client.stream(
            "GET", f"/api/meetings/{run.meeting_id}/session/stream"
        ) as stream:
            run.stream_body = "".join(stream.iter_text())

        for nudge_id, disposition in fixtures.DISPOSITIONS:
            recorded = client.post(
                f"/api/meetings/{run.meeting_id}/nudges/{nudge_id}/disposition",
                json={"disposition": disposition},
            )
            assert recorded.status_code in (200, 201), recorded.text

        # Everything from here runs on its own: the second engine finishing is
        # what starts the write-up.
        transcribed = client.post(
            f"/api/sessions/{run.meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-discovery-1"},
        )
        assert transcribed.status_code == 201, transcribed.text
        run.transcripts = transcribed.json()

        yield run


def test_both_engines_transcribed_the_whole_session(journey) -> None:
    assert len(journey.transcripts) == 2
    assert all(row["status"] == "complete" for row in journey.transcripts)
    for row in journey.transcripts:
        assert len(row["segments"]) == len(fixtures.UTTERANCES)


def test_the_clients_own_words_reached_the_transcriber(journey) -> None:
    """FR-2.9. The keyterm handshake is the one preparation step with teeth."""

    for _name, transcribe in journey.engines:
        assert transcribe.sent_keyterms, "the engine was never called"
        assert sorted(transcribe.sent_keyterms[0]) == sorted(VOCABULARY)


def test_the_panel_was_told_its_mode_before_any_suggestion(journey) -> None:
    """A quiet panel means two different things; the lane frame settles which."""

    frames = [
        line.removeprefix("event: ")
        for line in journey.stream_body.splitlines()
        if line.startswith("event: ")
    ]
    assert frames[0] == "lane"
    assert frames.count("nudge") == 4
    assert "coverage" in frames


def test_every_disagreement_between_the_engines_is_surfaced(journey) -> None:
    """FR-2.8, including the single-word ones that change what a requirement means."""

    alignment = journey.get(f"/api/meetings/{journey.meeting_id}/record/divergences")
    spans = alignment["spans"]
    assert len(spans) == 7, "seven utterances carry a planted mishearing"

    dock = next(s for s in spans if "dock rule" in s["reference_text"])
    assert "fifteen minute dock rule" in dock["reference_text"]
    assert "fifty minute dock rule" in dock["other_text"]
    assert dock["is_divergent"] is True
    # And the score still says how far apart they are, which is what an
    # operator sorts by.
    assert dock["agreement_score"] > 0.9


def test_the_audio_is_destroyed_and_the_destruction_recorded(journey) -> None:
    """NFR-2.4: shown, not asserted — the deletion has its own record."""

    destruction = journey.get(f"/api/sessions/{journey.meeting_id}/audio-destruction")
    assert destruction["status"] == "complete"
    assert destruction["audio_ref"] == "fixture://northgate-discovery-1"
    assert destruction["completed_at"] is not None


def test_the_write_up_ran_every_stage_in_order(journey) -> None:
    completion = journey.get(f"/api/meetings/{journey.meeting_id}/debrief/completion")
    assert completion["complete"] is True, completion.get("reason")
    assert completion["stopped_at"] is None
    assert completion["stages_completed"] == [
        "diarization",
        "audio-discard",
        "cleaning",
        "translation",
        "classification",
        "coverage-matrix",
        "analyst-chain",
        "citation-binding",
        "state-merge",
    ]


def test_the_four_documents_were_produced(journey) -> None:
    artifacts = journey.get(f"/api/meetings/{journey.meeting_id}/artifacts")
    kinds = {row["artifact_type"] for row in artifacts}
    assert {"open_questions", "decision_log", "project_brief", "follow_up_email"} <= kinds


def test_every_claim_carries_the_moment_it_came_from(journey) -> None:
    """FR-8.7: a claim without a source cannot be saved, so none may be here."""

    claims = journey.get(f"/api/sessions/{journey.meeting_id}/open-questions")
    claims += journey.get(f"/api/sessions/{journey.meeting_id}/decision-log")
    assert len(claims) == 6

    for claim in claims:
        assert claim["citations"], claim["text"]
        citation = claim["citations"][0]
        assert citation["quoted_text"], claim["text"]
        assert citation["speaker_tag"].startswith("SPEAKER_")
        # The quote is the transcript's own words, not the chain's account of
        # them: `resolve_citations` reads it back off the utterance.
        assert citation["quoted_text"] in {
            text for _s, _e, _speaker, text in fixtures.UTTERANCES
        }


def test_a_claim_says_whether_it_was_said_or_worked_out(journey) -> None:
    """FR-8.8. Blurring the two would make every document untrustworthy."""

    claims = journey.get(f"/api/sessions/{journey.meeting_id}/open-questions")
    provenances = {claim["provenance"] for claim in claims}
    assert provenances <= {"stated", "inferred"}
    assert "stated" in provenances


def test_the_speakers_were_told_apart(journey) -> None:
    """Diarization is what makes 'who said it' answerable at all."""

    claims = journey.get(f"/api/sessions/{journey.meeting_id}/decision-log")
    speakers = {claim["citations"][0]["speaker_tag"] for claim in claims}
    assert len(speakers) > 1, f"every decision attributed to {speakers}"


def test_what_was_settled_carries_into_the_next_meeting(journey) -> None:
    """FR-8.9: the state merge is what makes a second meeting worth having."""

    state = journey.get(f"/api/engagements/{journey.engagement_id}/requirements-state")
    assert state["confirmed_requirements"], "nothing carried forward"
