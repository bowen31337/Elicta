"""Tests for the BMAD analyst chain orchestrator and citation resolution (PRD FR-4.1, FR-8)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.modules.debrief.pipeline.bmad_analyst import (
    normalize_provenance,
    resolve_citations,
    run_bmad_analyst_chain,
)
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadAnalystChainStatus,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    ClaimProvenance,
    ClassifiedUtterance,
    SessionBmadAnalystChain,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_classified_utterances() -> list[ClassifiedUtterance]:
    return [
        ClassifiedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="um we need the thing by friday",
            cleaned_text="We need the thing by Friday.",
            section_key="timeline",
        ),
        ClassifiedUtterance(
            utterance_id="utt-2",
            session_id="session-1",
            start_seconds=1.0,
            end_seconds=2.0,
            speaker_tag="bob",
            verbatim_text="yeah that works for me",
            cleaned_text="Yeah, that works for me.",
            section_key="timeline",
        ),
    ]


def make_output(
    *,
    open_question_citations: list[str] | None = None,
    decision_citations: list[str] | None = None,
    brief_citations: list[str] | None = None,
    email_citations: list[str] | None = None,
    provenance: str = "stated",
) -> BmadAnalystChainOutput:
    return BmadAnalystChainOutput(
        open_questions=[
            BmadOpenQuestionDraft(
                text="What is the hard deadline?",
                impact_rank=1,
                provenance=provenance,
                citation_utterance_ids=open_question_citations or ["utt-1"],
            )
        ],
        decisions=[
            BmadDecisionDraft(
                text="Ship by Friday",
                decided_by="bob",
                provenance=provenance,
                citation_utterance_ids=decision_citations or ["utt-2"],
            )
        ],
        project_brief=BmadProjectBriefDraft(
            body="The client needs the thing by Friday.",
            provenance=provenance,
            citation_utterance_ids=brief_citations or ["utt-1"],
        ),
        follow_up_email=BmadFollowUpEmailDraft(
            subject="Recap and next steps",
            body="Thanks for the time today.",
            provenance=provenance,
            citation_utterance_ids=email_citations or ["utt-1", "utt-2"],
        ),
    )


def make_run_chain(output: BmadAnalystChainOutput | None = None, *, fail: bool = False):
    async def run_chain(session_id: str, utterances: list[ClassifiedUtterance]) -> BmadAnalystChainOutput:
        if fail:
            raise RuntimeError("analyst chain timed out")
        return output or make_output()

    return run_chain


def test_a_successful_run_persists_the_full_artifact_set_with_resolved_citations():
    saved: list[SessionBmadAnalystChain] = []

    async def save(record: SessionBmadAnalystChain) -> None:
        saved.append(record)

    result = asyncio.run(
        run_bmad_analyst_chain(
            "session-1",
            make_classified_utterances(),
            "chain-a",
            make_run_chain(),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystChainStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "chain-a"
    assert result.artifacts is not None

    question = result.artifacts.open_questions[0]
    assert question.text == "What is the hard deadline?"
    assert question.provenance == ClaimProvenance.STATED
    assert question.citations[0].utterance_id == "utt-1"
    assert question.citations[0].speaker_tag == "alice"
    assert question.citations[0].quoted_text == "um we need the thing by friday"

    decision = result.artifacts.decisions[0]
    assert decision.decided_by == "bob"
    assert decision.citations[0].utterance_id == "utt-2"

    assert result.artifacts.project_brief.body == "The client needs the thing by Friday."
    assert result.artifacts.follow_up_email.subject == "Recap and next steps"
    assert len(result.artifacts.follow_up_email.citations) == 2
    assert saved == [result]


def test_a_citation_naming_an_unknown_utterance_fails_the_run_instead_of_persisting_it():
    async def save(record: SessionBmadAnalystChain) -> None:
        pass

    result = asyncio.run(
        run_bmad_analyst_chain(
            "session-1",
            make_classified_utterances(),
            "chain-a",
            make_run_chain(make_output(open_question_citations=["utt-does-not-exist"])),
            save,
        )
    )

    assert result.status == BmadAnalystChainStatus.FAILED
    assert result.artifacts is None
    assert "utt-does-not-exist" in result.error


def test_a_failed_chain_persists_a_failed_record_with_no_artifacts():
    saved: list[SessionBmadAnalystChain] = []

    async def save(record: SessionBmadAnalystChain) -> None:
        saved.append(record)

    result = asyncio.run(
        run_bmad_analyst_chain(
            "session-1",
            make_classified_utterances(),
            "chain-a",
            make_run_chain(fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystChainStatus.FAILED
    assert result.engine == "chain-a"
    assert result.artifacts is None
    assert result.error == "analyst chain timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_an_unrecognized_provenance_value_is_normalized_to_inferred_not_left_as_is():
    result = asyncio.run(
        run_bmad_analyst_chain(
            "session-1",
            make_classified_utterances(),
            "chain-a",
            make_run_chain(make_output(provenance="probably-stated")),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.artifacts.open_questions[0].provenance == ClaimProvenance.INFERRED
    assert result.artifacts.decisions[0].provenance == ClaimProvenance.INFERRED
    assert result.artifacts.project_brief.provenance == ClaimProvenance.INFERRED
    assert result.artifacts.follow_up_email.provenance == ClaimProvenance.INFERRED


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    result = asyncio.run(
        run_bmad_analyst_chain(
            "session-1",
            make_classified_utterances(),
            "chain-a",
            make_run_chain(),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.completed_at >= result.requested_at


def test_normalize_provenance_passes_through_stated():
    assert normalize_provenance("stated") == ClaimProvenance.STATED


@pytest.mark.parametrize("raw", ["inferred", "", "STATED", "unknown"])
def test_normalize_provenance_falls_back_to_inferred_for_anything_else(raw: str):
    assert normalize_provenance(raw) == ClaimProvenance.INFERRED


def test_resolve_citations_grounds_every_field_in_the_actual_utterance():
    utterances_by_id = {u.utterance_id: u for u in make_classified_utterances()}

    citations = resolve_citations(["utt-2"], utterances_by_id)

    assert len(citations) == 1
    citation = citations[0]
    assert citation.session_id == "session-1"
    assert citation.speaker_tag == "bob"
    assert citation.start_seconds == 1.0
    assert citation.end_seconds == 2.0
    assert citation.quoted_text == "yeah that works for me"


def test_resolve_citations_raises_for_an_unknown_utterance_id():
    utterances_by_id = {u.utterance_id: u for u in make_classified_utterances()}

    with pytest.raises(ValueError):
        resolve_citations(["nope"], utterances_by_id)
