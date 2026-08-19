import asyncio
from datetime import UTC, datetime

from app.core.consent.confirmation import record_consent_confirmation
from app.core.consent.models import ConsentRecord


def test_record_consent_confirmation_persists_meeting_operator_and_timestamp():
    saved: list[ConsentRecord] = []

    async def save(record: ConsentRecord) -> None:
        saved.append(record)

    fixed_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    record = asyncio.run(
        record_consent_confirmation("m1", "operator-42", save, confirmed_at=fixed_time)
    )

    assert record.meeting_id == "m1"
    assert record.confirmed_by == "operator-42"
    assert record.confirmed_at == fixed_time
    assert saved == [record]


def test_record_consent_confirmation_defaults_to_current_time():
    async def save(record: ConsentRecord) -> None:
        pass

    before = datetime.now(UTC)
    record = asyncio.run(record_consent_confirmation("m1", "operator-1", save))
    after = datetime.now(UTC)

    assert before <= record.confirmed_at <= after
