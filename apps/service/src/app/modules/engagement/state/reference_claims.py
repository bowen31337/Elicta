"""Lets a user mark a reference claim to verify with the client this session (PRD FR-3.12).

No durable store for reference claims exists yet in this codebase, so
`set_verify_with_client` takes the actual lookup and persistence as injected
`load`/`save` callables, mirroring every other stage in this module: whoever
wires the app factory supplies the real, persistence-backed implementations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .models import ReferenceClaim

LoadReferenceClaim = Callable[[str, str], Awaitable[ReferenceClaim | None]]
SaveReferenceClaim = Callable[[ReferenceClaim], Awaitable[None]]


async def set_verify_with_client(
    engagement_id: str,
    claim_id: str,
    verify_with_client: bool,
    load: LoadReferenceClaim,
    save: SaveReferenceClaim,
) -> ReferenceClaim:
    """Persist `verify_with_client` on one reference claim (PRD FR-3.12).

    Raises `ValueError` if `load` finds no claim with `claim_id` under
    `engagement_id`, rather than silently persisting a flag against a claim
    that doesn't exist. On success, the updated claim is both persisted via
    `save` and returned, so a caller doesn't need a second round trip to see
    the new flag value.
    """

    claim = await load(engagement_id, claim_id)
    if claim is None:
        raise ValueError(f"no reference claim {claim_id!r} for engagement {engagement_id!r}")

    updated = claim.model_copy(update={"verify_with_client": verify_with_client})
    await save(updated)
    return updated
