"""Per-engagement processing-region pinning (PRD NFR-2.2).

Data residency is agreed with the client once, at engagement setup, and
every external call the service makes on that engagement's behalf must
land in that same region for as long as the engagement runs. Holding the
pin in one registry keyed by ``engagement_id`` — rather than trusting each
call site to pass the right region — is what makes "pinned per engagement"
a guarantee the chokepoint enforces, instead of a convention call sites
could drift from.
"""

from __future__ import annotations


class EngagementRegionRegistry:
    """Maps ``engagement_id`` to the processing region pinned for it."""

    def __init__(self, regions: dict[str, str] | None = None) -> None:
        self._regions: dict[str, str] = dict(regions or {})

    def pin(self, engagement_id: str, region: str) -> None:
        """Pins ``engagement_id`` to ``region``.

        Repinning to a *different* region is rejected outright: a mid-
        engagement region change is exactly the residency drift NFR-2.2
        exists to prevent. Pinning the same region again is a no-op, so
        callers don't need to track whether they've already pinned it.
        """

        existing = self._regions.get(engagement_id)
        if existing is not None and existing != region:
            raise ValueError(
                f"engagement {engagement_id!r} is already pinned to region "
                f"{existing!r}, cannot repin to {region!r}"
            )
        self._regions[engagement_id] = region

    def region_for(self, engagement_id: str) -> str | None:
        return self._regions.get(engagement_id)
