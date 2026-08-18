"""End-to-end test of the full debrief journey: record-path transcription completes,
every later pipeline stage runs over that transcript's real output, and every
requirement claim the BMAD analyst chain produces carries a citation grounded in it
(PRD FR-2.5/2.6, FR-7.2, FR-8.2, FR-8.7, FR-8.7a, FR-8.10).

Diarization, cleaning, translation, and section classification have no HTTP surface
yet — each stage's own module docstring says so — so this test drives those stages
directly with the same real pipeline functions the (not-yet-existing) orchestrator
would call, the way `test_multi_meeting_arc.py` drives `merge_requirements_state_forward`
directly. Everything that *is* wired in `conftest.py` — record-path transcription,
full PRD generation, the per-session artifact reads, and citation-row writes — is
driven through the real HTTP surface via `client`, not called directly.

The whole point of the journey is traceability: every open question, decision,
project brief, and follow-up email the chain produces must cite text that actually
came back from the record-path transcript, never a citation the chain merely
asserted.
"""

from __future__ import annotations

import asyncio
import importlib

from app.modules.debrief.artifacts.matrix import build_coverage_matrix
from app.modules.debrief.artifacts.models import CoverageCitation, CoverageMatrixStatus, FillState
from app.modules.debrief.pipeline.bmad_analyst import run_bmad_analyst_chain
from app.modules.debrief.pipeline.citations import build_citation_rows
from app.modules.debrief.pipeline.classification import run_section_classification
from app.modules.debrief.pipeline.cleaning import run_transcript_cleaning
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadAnalystChainStatus,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    ClaimProvenance,
    DiarizationOutput,
    SessionBmadAnalystChain,
    SpeakerTurn,
    TemplateSection,
    TranscriptSpan,
    TranslationOutcome,
)
from app.modules.debrief.pipeline.service import run_diarization
from app.modules.debrief.pipeline.translation import run_transcript_translation
from fastapi.testclient import TestClient

from conftest import Backend

_asr_citation = importlib.import_module("app.modules.asr-record.citation")
cite_record_path_span = _asr_citation.cite_record_path_span


async def _noop_save(_: object) -> None:
    """Discard a stage's persisted record: nothing downstream in this test reads it back."""


def test_debrief_journey_generates_artifacts_with_a_citation_for_every_claim(
    client: TestClient, backend: Backend
) -> None:
    session_id = "session-journey-1"
    engagement_id = "engagement-journey-1"

    # 1. Record-path transcription completes, over the real HTTP surface (PRD FR-2.5/2.6).
    response = client.post(
        f"/api/sessions/{session_id}/record-path-transcript",
        json={"audio_ref": "s3://recordings/journey-1"},
    )
    assert response.status_code == 201
    transcripts = response.json()
    assert [t["engine"] for t in transcripts] == ["engine-a", "engine-b"]
    assert all(t["status"] == "complete" for t in transcripts)

    saved_transcripts = backend.record_path_transcripts[session_id]
    primary_transcript = next(t for t in saved_transcripts if t.engine == "engine-a")
    assert primary_transcript.text == "hello there"

    # 2. Diarization tags each of the record path's own spans with a speaker (PRD FR-7.2).
    spans = [
        TranscriptSpan(start_seconds=segment.start_seconds, end_seconds=segment.end_seconds, text=segment.text)
        for segment in primary_transcript.segments
    ]

    async def diarize(_session_id: str, _audio_ref: str) -> DiarizationOutput:
        return DiarizationOutput(
            engine="diarizer-a",
            turns=[SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="client")],
        )

    diarization = asyncio.run(
        run_diarization(session_id, "s3://recordings/journey-1", spans, "diarizer-a", diarize, _noop_save)
    )
    assert diarization.utterances[0].speaker_tag == "client"

    # 3. Cleaning, translation, and section classification run over that diarized transcript.
    async def clean(_session_id: str, utterances: list) -> list[str]:
        return [utterance.text for utterance in utterances]

    cleaning = asyncio.run(
        run_transcript_cleaning(session_id, diarization.utterances, "cleaner-a", clean, _noop_save)
    )

    async def translate(_session_id: str, utterances: list, _document_language: str) -> list[TranslationOutcome]:
        return [TranslationOutcome(original_language="en") for _ in utterances]

    translation = asyncio.run(
        run_transcript_translation(session_id, cleaning.utterances, "en", "translator-a", translate, _noop_save)
    )

    slots = [TemplateSection(key="scope", title="Scope")]

    async def classify(_session_id: str, utterances: list, _slots: list[TemplateSection]) -> list[str]:
        return ["scope" for _ in utterances]

    classification = asyncio.run(
        run_section_classification(session_id, translation.utterances, slots, "classifier-a", classify, _noop_save)
    )
    assert classification.slots[0].fill_state == FillState.FILLED

    # 4. The coverage matrix grounds its one filled slot in the record-path transcript (PRD FR-8.2, FR-2.7).
    async def cite_filled_slot(session_id: str, start_seconds: float, end_seconds: float) -> CoverageCitation:
        reference = cite_record_path_span(primary_transcript, start_seconds, end_seconds)
        return CoverageCitation(**reference.model_dump())

    matrices: list = []

    async def save_matrix(matrix) -> None:
        matrices.append(matrix)

    matrix = asyncio.run(build_coverage_matrix(classification, cite_filled_slot, save_matrix))
    assert matrix.status == CoverageMatrixStatus.COMPLETE
    assert matrix.is_fully_covered
    assert matrix.entries[0].citations[0].quoted_text == "hello there"
    backend.coverage_matrices[engagement_id] = matrices

    # 5. The BMAD analyst chain produces the full artifact set, every claim grounded (PRD FR-4.1, FR-8).
    utterance_id = classification.utterances[0].utterance_id

    async def run_chain(_session_id: str, _utterances: list) -> BmadAnalystChainOutput:
        return BmadAnalystChainOutput(
            open_questions=[
                BmadOpenQuestionDraft(
                    text="what is the exact launch date?",
                    impact_rank=1,
                    provenance=ClaimProvenance.STATED.value,
                    citation_utterance_ids=[utterance_id],
                )
            ],
            decisions=[
                BmadDecisionDraft(
                    text="proceed with the plan",
                    decided_by="client",
                    provenance=ClaimProvenance.STATED.value,
                    citation_utterance_ids=[utterance_id],
                )
            ],
            project_brief=BmadProjectBriefDraft(
                body="Project brief drafted from the debrief session.",
                provenance=ClaimProvenance.STATED.value,
                citation_utterance_ids=[utterance_id],
            ),
            follow_up_email=BmadFollowUpEmailDraft(
                subject="Next steps",
                body="Thanks for the debrief session.",
                provenance=ClaimProvenance.STATED.value,
                citation_utterance_ids=[utterance_id],
            ),
        )

    async def save_chain(chain: SessionBmadAnalystChain) -> None:
        backend.bmad_chains[session_id] = chain

    chain = asyncio.run(
        run_bmad_analyst_chain(session_id, classification.utterances, "claude", run_chain, save_chain)
    )
    assert chain.status == BmadAnalystChainStatus.COMPLETE
    artifacts = chain.artifacts
    assert artifacts is not None

    all_claim_citations = [
        artifacts.open_questions[0].citations,
        artifacts.decisions[0].citations,
        artifacts.project_brief.citations,
        artifacts.follow_up_email.citations,
    ]
    for citations in all_claim_citations:
        assert citations, "every requirement claim must carry at least one citation"
        assert citations[0].quoted_text == "hello there"
        assert citations[0].utterance_id == utterance_id

    # 6. Every per-session artifact read reflects those same grounded citations, over HTTP.
    response = client.get(f"/api/sessions/{session_id}/project-brief")
    assert response.status_code == 200
    assert response.json()["citations"][0]["quoted_text"] == "hello there"

    response = client.get(f"/api/sessions/{session_id}/decision-log")
    assert response.status_code == 200
    assert response.json()[0]["citations"][0]["quoted_text"] == "hello there"

    response = client.get(f"/api/sessions/{session_id}/open-questions")
    assert response.status_code == 200
    assert response.json()[0]["citations"][0]["quoted_text"] == "hello there"

    response = client.get(f"/api/sessions/{session_id}/follow-up-email")
    assert response.status_code == 200
    assert response.json()["citations"][0]["quoted_text"] == "hello there"

    # 7. Full PRD generation clears the coverage gate and returns the same grounded artifacts (PRD FR-8.10).
    backend.prd_to_generate = artifacts
    response = client.post(f"/api/engagements/{engagement_id}/prd")
    assert response.status_code == 201
    prd_body = response.json()
    assert prd_body["open_questions"][0]["citations"][0]["quoted_text"] == "hello there"
    assert prd_body["decisions"][0]["citations"][0]["quoted_text"] == "hello there"
    assert prd_body["project_brief"]["citations"][0]["quoted_text"] == "hello there"
    assert prd_body["follow_up_email"]["citations"][0]["quoted_text"] == "hello there"

    # 8. Every claim persists its own citations-table row (PRD FR-8.7): the citations table is
    #    the durable record that "every requirement claim shows a citation" actually means.
    rows = build_citation_rows(session_id, artifacts)
    assert {row.claim_kind.value for row in rows} == {
        "open_question",
        "decision",
        "project_brief",
        "follow_up_email",
    }

    for row in rows:
        response = client.post(f"/api/sessions/{session_id}/citations", json=row.model_dump(mode="json"))
        assert response.status_code == 201

    assert len(backend.citation_rows) == len(rows)
    assert all(row.quoted_text == "hello there" for row in backend.citation_rows)
