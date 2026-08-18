"""Tests for binding every BMAD analyst claim to a citations-table row (PRD FR-8.7)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.modules.debrief.pipeline.citations import build_citation_rows, persist_citation_table
from app.modules.debrief.pipeline.models import (
    ArtifactCitation,
    BmadArtifactSet,
    CitationTableStatus,
    ClaimKind,
    ClaimProvenance,
    DecisionLogEntry,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
    SessionCitationTable,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_citation(
    utterance_id: str = "utt-1",
    speaker_tag: str = "alice",
    *,
    original_language: str = "en",
    translated_text: str | None = None,
) -> ArtifactCitation:
    return ArtifactCitation(
        utterance_id=utterance_id,
        session_id="session-1",
        start_seconds=0.0,
        end_seconds=1.0,
        speaker_tag=speaker_tag,
        quoted_text="um we need the thing by friday",
        original_language=original_language,
        translated_text=translated_text,
    )


def make_artifacts(
    *,
    open_question_citations: list[ArtifactCitation] | None = None,
    decision_citations: list[ArtifactCitation] | None = None,
    brief_citations: list[ArtifactCitation] | None = None,
    email_citations: list[ArtifactCitation] | None = None,
) -> BmadArtifactSet:
    return BmadArtifactSet(
        open_questions=[
            OpenQuestion(
                text="What is the hard deadline?",
                impact_rank=1,
                provenance=ClaimProvenance.STATED,
                citations=open_question_citations if open_question_citations is not None else [make_citation()],
            )
        ],
        decisions=[
            DecisionLogEntry(
                text="Ship by Friday",
                decided_by="bob",
                provenance=ClaimProvenance.STATED,
                citations=decision_citations if decision_citations is not None else [make_citation("utt-2", "bob")],
            )
        ],
        project_brief=ProjectBriefDraft(
            body="The client needs the thing by Friday.",
            provenance=ClaimProvenance.STATED,
            citations=brief_citations if brief_citations is not None else [make_citation()],
        ),
        follow_up_email=FollowUpEmailDraft(
            subject="Recap and next steps",
            body="Thanks for the time today.",
            provenance=ClaimProvenance.STATED,
            citations=(
                email_citations if email_citations is not None else [make_citation(), make_citation("utt-2", "bob")]
            ),
        ),
    )


def test_build_citation_rows_produces_one_row_per_citation_across_every_claim():
    rows = build_citation_rows("session-1", make_artifacts())

    kinds = [row.claim_kind for row in rows]
    assert kinds.count(ClaimKind.OPEN_QUESTION) == 1
    assert kinds.count(ClaimKind.DECISION) == 1
    assert kinds.count(ClaimKind.PROJECT_BRIEF) == 1
    assert kinds.count(ClaimKind.FOLLOW_UP_EMAIL) == 2

    open_question_row = next(row for row in rows if row.claim_kind == ClaimKind.OPEN_QUESTION)
    assert open_question_row.session_id == "session-1"
    assert open_question_row.claim_index == 0
    assert open_question_row.utterance_id == "utt-1"
    assert open_question_row.speaker_tag == "alice"
    assert open_question_row.start_seconds == 0.0
    assert open_question_row.end_seconds == 1.0
    assert open_question_row.original_language == "en"
    assert open_question_row.translated_text is None


def test_build_citation_rows_carries_the_original_language_and_translation_onto_a_cross_language_row():
    rows = build_citation_rows(
        "session-1",
        make_artifacts(
            decision_citations=[
                make_citation(
                    "utt-2", "bob", original_language="es", translated_text="We need this by Friday."
                )
            ]
        ),
    )

    decision_row = next(row for row in rows if row.claim_kind == ClaimKind.DECISION)
    assert decision_row.quoted_text == "um we need the thing by friday"
    assert decision_row.original_language == "es"
    assert decision_row.translated_text == "We need this by Friday."


@pytest.mark.parametrize(
    "empty_field",
    ["open_question_citations", "decision_citations", "brief_citations", "email_citations"],
)
def test_build_citation_rows_raises_for_a_claim_with_no_citations(empty_field: str):
    artifacts = make_artifacts(**{empty_field: []})

    with pytest.raises(ValueError):
        build_citation_rows("session-1", artifacts)


def test_a_successful_run_persists_a_complete_citation_table_with_a_row_for_every_claim():
    saved: list[SessionCitationTable] = []

    async def save(record: SessionCitationTable) -> None:
        saved.append(record)

    result = asyncio.run(
        persist_citation_table("session-1", make_artifacts(), save, requested_at=FIXED)
    )

    assert result.status == CitationTableStatus.COMPLETE
    assert result.session_id == "session-1"
    assert len(result.rows) == 5
    assert {ClaimKind.OPEN_QUESTION, ClaimKind.DECISION, ClaimKind.PROJECT_BRIEF, ClaimKind.FOLLOW_UP_EMAIL} == {
        row.claim_kind for row in result.rows
    }
    assert result.requested_at == FIXED
    assert saved == [result]


def test_a_claim_with_no_citations_fails_the_run_instead_of_persisting_a_gap():
    saved: list[SessionCitationTable] = []

    async def save(record: SessionCitationTable) -> None:
        saved.append(record)

    result = asyncio.run(
        persist_citation_table("session-1", make_artifacts(decision_citations=[]), save, requested_at=FIXED)
    )

    assert result.status == CitationTableStatus.FAILED
    assert result.rows == []
    assert "decision" in result.error
    assert saved == [result]


def test_completed_at_is_not_before_requested_at():
    async def save(record: SessionCitationTable) -> None:
        pass

    result = asyncio.run(persist_citation_table("session-1", make_artifacts(), save))

    assert result.completed_at >= result.requested_at
