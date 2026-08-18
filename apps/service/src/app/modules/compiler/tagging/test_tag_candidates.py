"""Tests for validating and persisting the PRD FR-4.2 tag set across a batch of candidates."""

from __future__ import annotations

import asyncio

import pytest

from app.modules.compiler.tagging.models import (
    CandidateTagging,
    CandidateTags,
    TaggedCandidate,
)
from app.modules.compiler.tagging.tag_candidates import (
    persist_candidate_tags,
    tag_candidates,
)


def make_tagging(candidate_id: str, **overrides) -> CandidateTagging:
    defaults = {
        "template_section": "scope",
        "trigger_types": ["unquantified_adjective"],
        "priority": 1,
        "requires": [],
    }
    defaults.update(overrides)
    return CandidateTagging(id=candidate_id, tags=CandidateTags(**defaults))


def test_tag_candidates_preserves_each_candidates_tag_fields():
    taggings = [
        make_tagging(
            "candidate-1",
            template_section="scope",
            trigger_types=["a", "b"],
            priority=2,
        ),
        make_tagging("candidate-2", requires=["candidate-1"]),
    ]

    tagged = tag_candidates(taggings)

    assert tagged[0] == TaggedCandidate(
        id="candidate-1",
        template_section="scope",
        trigger_types=["a", "b"],
        priority=2,
        requires=[],
    )
    assert tagged[1].id == "candidate-2"
    assert tagged[1].requires == ["candidate-1"]


def test_a_requires_id_naming_another_batch_member_is_accepted():
    taggings = [
        make_tagging("candidate-1"),
        make_tagging("candidate-2", requires=["candidate-1"]),
    ]

    tagged = tag_candidates(taggings)

    assert [c.id for c in tagged] == ["candidate-1", "candidate-2"]


def test_a_requires_id_naming_no_candidate_in_the_batch_is_rejected():
    taggings = [make_tagging("candidate-1", requires=["candidate-missing"])]

    with pytest.raises(ValueError, match="candidate-missing"):
        tag_candidates(taggings)


def test_a_candidate_naming_itself_as_its_own_prerequisite_is_rejected():
    taggings = [make_tagging("candidate-1", requires=["candidate-1"])]

    with pytest.raises(ValueError, match="candidate-1"):
        tag_candidates(taggings)


def test_a_candidate_with_no_trigger_types_is_rejected():
    with pytest.raises(ValueError):
        make_tagging("candidate-1", trigger_types=[])


def test_persist_candidate_tags_saves_every_validated_row():
    saved: list[TaggedCandidate] = []

    async def save(candidate: TaggedCandidate) -> None:
        saved.append(candidate)

    taggings = [
        make_tagging("candidate-1"),
        make_tagging("candidate-2", requires=["candidate-1"]),
    ]

    result = asyncio.run(persist_candidate_tags(taggings, save))

    assert saved == result
    assert [c.id for c in saved] == ["candidate-1", "candidate-2"]


def test_persist_candidate_tags_saves_nothing_when_the_batch_fails_validation():
    saved: list[TaggedCandidate] = []

    async def save(candidate: TaggedCandidate) -> None:
        saved.append(candidate)

    taggings = [make_tagging("candidate-1", requires=["candidate-missing"])]

    with pytest.raises(ValueError):
        asyncio.run(persist_candidate_tags(taggings, save))

    assert saved == []
