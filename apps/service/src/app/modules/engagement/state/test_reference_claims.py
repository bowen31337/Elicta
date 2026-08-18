"""Tests for marking a reference claim to verify with the client this session (PRD FR-3.12)."""

from __future__ import annotations

import asyncio

from app.modules.engagement.state.models import ReferenceClaim
from app.modules.engagement.state.reference_claims import set_verify_with_client


def make_claim(
    claim_id: str = "claim-1",
    engagement_id: str = "engagement-1",
    text: str = "the client uses SAP",
    verify_with_client: bool = False,
) -> ReferenceClaim:
    return ReferenceClaim(
        claim_id=claim_id, engagement_id=engagement_id, text=text, verify_with_client=verify_with_client
    )


def test_marking_a_claim_to_verify_with_client_persists_the_flag_as_true():
    existing = make_claim()
    saved: list[ReferenceClaim] = []

    async def load(engagement_id: str, claim_id: str) -> ReferenceClaim | None:
        assert (engagement_id, claim_id) == ("engagement-1", "claim-1")
        return existing

    async def save(claim: ReferenceClaim) -> None:
        saved.append(claim)

    result = asyncio.run(set_verify_with_client("engagement-1", "claim-1", True, load, save))

    assert result.verify_with_client is True
    assert result.claim_id == "claim-1"
    assert result.engagement_id == "engagement-1"
    assert result.text == existing.text
    assert saved == [result]


def test_unmarking_a_previously_flagged_claim_persists_the_flag_as_false():
    existing = make_claim(verify_with_client=True)

    async def load(engagement_id: str, claim_id: str) -> ReferenceClaim | None:
        return existing

    async def save(claim: ReferenceClaim) -> None:
        pass

    result = asyncio.run(set_verify_with_client("engagement-1", "claim-1", False, load, save))

    assert result.verify_with_client is False


def test_marking_a_claim_that_does_not_exist_for_the_engagement_raises_instead_of_persisting_anything():
    saved: list[ReferenceClaim] = []

    async def load(engagement_id: str, claim_id: str) -> ReferenceClaim | None:
        return None

    async def save(claim: ReferenceClaim) -> None:
        saved.append(claim)

    try:
        asyncio.run(set_verify_with_client("engagement-1", "missing-claim", True, load, save))
        raised = False
    except ValueError:
        raised = True

    assert raised
    assert saved == []


def test_setting_the_flag_leaves_the_claims_other_fields_untouched():
    existing = make_claim(text="the client is migrating off Oracle")

    async def load(engagement_id: str, claim_id: str) -> ReferenceClaim | None:
        return existing

    async def save(claim: ReferenceClaim) -> None:
        pass

    result = asyncio.run(set_verify_with_client("engagement-1", "claim-1", True, load, save))

    assert result.text == "the client is migrating off Oracle"
    assert result.claim_id == existing.claim_id
    assert result.engagement_id == existing.engagement_id
