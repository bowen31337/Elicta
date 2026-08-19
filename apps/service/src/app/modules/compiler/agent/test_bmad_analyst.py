"""Tests for the offline BMAD Analyst pass and its PRD FR-4.1 candidate-count contract."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.modules.compiler.agent.bmad_analyst import (
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    build_bank_candidates,
    run_bmad_analyst_pass,
)
from app.modules.compiler.agent.models import (
    AnalystContextPack,
    BmadAnalystPassOutput,
    BmadAnalystPassStatus,
    BmadCandidateDraft,
    ContextPackDocument,
    EngagementBmadAnalystPass,
)
from app.modules.engagement.documents.models import DocumentStatus

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_context_pack() -> AnalystContextPack:
    return AnalystContextPack(
        engagement_id="engagement-1",
        sector="technology",
        project_type="greenfield",
        documents=[
            ContextPackDocument(
                document_id="doc-1",
                status=DocumentStatus.GROUND_TRUTH,
                text="The client wants a new billing system.",
            )
        ],
    )


def make_draft(index: int, **overrides) -> BmadCandidateDraft:
    defaults = {
        "template_section": "scope",
        "trigger_types": ["unquantified_adjective"],
        "phrasing": f"What does 'fast' mean for capability {index}?",
        "stub": f"clarify capability {index}",
        "lang": "en",
        "priority": index + 1,
    }
    defaults.update(overrides)
    return BmadCandidateDraft(**defaults)


def make_output(count: int) -> BmadAnalystPassOutput:
    return BmadAnalystPassOutput(candidates=[make_draft(i) for i in range(count)])


def make_run_chain(output: BmadAnalystPassOutput | None = None, *, fail: bool = False):
    async def run_chain(engagement_id: str, context_pack: AnalystContextPack) -> BmadAnalystPassOutput:
        if fail:
            raise RuntimeError("analyst pass timed out")
        return output if output is not None else make_output(MIN_CANDIDATES)

    return run_chain


def test_a_successful_run_persists_a_complete_record_with_assigned_ids():
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_bmad_analyst_pass(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_run_chain(make_output(MIN_CANDIDATES)),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystPassStatus.COMPLETE
    assert result.engagement_id == "engagement-1"
    assert result.engine == "analyst-a"
    assert result.candidates is not None
    assert len(result.candidates) == MIN_CANDIDATES
    assert result.candidates[0].id == "engagement-1-candidate-0"
    assert result.candidates[0].engagement_id == "engagement-1"
    assert saved == [result]


@pytest.mark.parametrize("count", [0, 1, 149, 301, 500])
def test_a_candidate_count_outside_150_to_300_fails_the_run(count: int):
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_bmad_analyst_pass(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_run_chain(make_output(count)),
            save,
        )
    )

    assert result.status == BmadAnalystPassStatus.FAILED
    assert result.candidates is None
    assert str(count) in result.error
    assert "FR-4.1" in result.error
    assert saved == [result]


@pytest.mark.parametrize("count", [MIN_CANDIDATES, 200, MAX_CANDIDATES])
def test_boundary_counts_within_150_to_300_succeed(count: int):
    result = asyncio.run(
        run_bmad_analyst_pass(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_run_chain(make_output(count)),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.status == BmadAnalystPassStatus.COMPLETE
    assert len(result.candidates) == count


def test_a_failed_chain_persists_a_failed_record_with_no_candidates():
    saved: list[EngagementBmadAnalystPass] = []

    async def save(record: EngagementBmadAnalystPass) -> None:
        saved.append(record)

    result = asyncio.run(
        run_bmad_analyst_pass(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_run_chain(fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == BmadAnalystPassStatus.FAILED
    assert result.engine == "analyst-a"
    assert result.candidates is None
    assert result.error == "analyst pass timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    result = asyncio.run(
        run_bmad_analyst_pass(
            "engagement-1",
            make_context_pack(),
            "analyst-a",
            make_run_chain(make_output(MIN_CANDIDATES)),
            lambda record: asyncio.sleep(0),
        )
    )

    assert result.completed_at >= result.requested_at


def test_build_bank_candidates_assigns_ids_in_order_and_preserves_tags():
    drafts = [
        make_draft(0, requires=["engagement-1-candidate-0"], authority_match=["cfo"], source_doc="doc-1"),
        make_draft(1),
    ]

    candidates = build_bank_candidates("engagement-1", drafts)

    assert [c.id for c in candidates] == ["engagement-1-candidate-0", "engagement-1-candidate-1"]
    assert all(c.engagement_id == "engagement-1" for c in candidates)
    assert candidates[0].requires == ["engagement-1-candidate-0"]
    assert candidates[0].authority_match == ["cfo"]
    assert candidates[0].source_doc == "doc-1"
    assert candidates[1].requires == []
    assert candidates[1].authority_match == []
    assert candidates[1].source_doc is None
