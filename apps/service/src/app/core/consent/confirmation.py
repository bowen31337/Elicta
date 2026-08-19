"""Recording per-meeting consent confirmations (PRD feature 246).

`gate.py` decides whether a meeting *needs* a fresh confirmation. This
module is what runs once the operator has actually given one: it builds the
`ConsentRecord` — timestamp plus the confirming operator — and hands it to
an injected `save` callback rather than writing to a persistence layer
directly, since that layer does not live in this package. Whoever wires the
app factory supplies the real, durable-storage-backed `save`.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.core.consent.models import ConsentRecord

SaveConsentRecord = Callable[[ConsentRecord], Awaitable[None]]


async def record_consent_confirmation(
    meeting_id: str,
    confirmed_by: str,
    save: SaveConsentRecord,
    *,
    confirmed_at: datetime | None = None,
) -> ConsentRecord:
    """Build the confirmation record for one meeting and persist it via `save`.

    `confirmed_at` defaults to the current UTC time; callers (tests, mainly)
    may supply a fixed value to assert on it deterministically.
    """

    record = ConsentRecord(
        meeting_id=meeting_id,
        confirmed_by=confirmed_by,
        confirmed_at=confirmed_at or datetime.now(UTC),
    )
    await save(record)
    return record
