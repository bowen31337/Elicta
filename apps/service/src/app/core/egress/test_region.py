import pytest

from app.core.egress.region import EngagementRegionRegistry


def test_an_unpinned_engagement_has_no_region():
    registry = EngagementRegionRegistry()

    assert registry.region_for("engagement-1") is None


def test_pinning_an_engagement_makes_its_region_lookupable():
    registry = EngagementRegionRegistry()

    registry.pin("engagement-1", "eu-west-1")

    assert registry.region_for("engagement-1") == "eu-west-1"


def test_pins_are_scoped_per_engagement():
    registry = EngagementRegionRegistry()

    registry.pin("engagement-1", "eu-west-1")
    registry.pin("engagement-2", "us-east-1")

    assert registry.region_for("engagement-1") == "eu-west-1"
    assert registry.region_for("engagement-2") == "us-east-1"


def test_repinning_the_same_region_is_a_no_op():
    registry = EngagementRegionRegistry()
    registry.pin("engagement-1", "eu-west-1")

    registry.pin("engagement-1", "eu-west-1")

    assert registry.region_for("engagement-1") == "eu-west-1"


def test_repinning_a_different_region_is_rejected():
    registry = EngagementRegionRegistry()
    registry.pin("engagement-1", "eu-west-1")

    with pytest.raises(ValueError, match="already pinned"):
        registry.pin("engagement-1", "us-east-1")

    assert registry.region_for("engagement-1") == "eu-west-1"


def test_a_registry_can_be_seeded_with_existing_pins():
    registry = EngagementRegionRegistry({"engagement-1": "eu-west-1"})

    assert registry.region_for("engagement-1") == "eu-west-1"
