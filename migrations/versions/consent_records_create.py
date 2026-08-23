"""create consent_records table

Revision ID: consent_records
Revises: candidate_prune_marks
Create Date: 2026-08-23

The record of who confirmed that a client was told they were being recorded,
and when. `ConsentRecord` has described itself as "durable proof" since it was
written, and it was not: the confirmations lived in a plain list on `Backend`
with no table behind them, so a restart lost the answer to "did we have
permission for this?" — and, because the gate's own answer was kept in a
second in-memory field, lost the open gate with it. A meeting that had properly
confirmed consent came back asking for it again.

Unlike a document or a vocabulary term, this cannot be re-entered from a
source. It describes a moment.

Two deliberate absences, both different from every other table here:

`meeting_id` is **not** a foreign key. This is an audit record *about* a
meeting id, and cascading it away with the row it describes would destroy the
evidence together with its subject.

There is **no `deleted_at`**. The soft-delete convention exists so an operator
can take something out of a list they own; a record of who took responsibility
for recording a client is not theirs to withdraw. `soft_delete_marks` left open
the question of whether a real erasure should also destroy consent records —
this answers only that a routine deletion must not.

`confirmed_at` is text rather than a timestamp on purpose. The value is
`datetime.now(UTC)`, timezone-aware, and SQLite's DateTime stores naive — a
round trip would silently drop the offset from a legally significant instant
and read it back as an ambiguous local time. ISO-8601 text is exact on every
backend a deployment might be pointed at.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "consent_records"
down_revision = "candidate_prune_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consent_records",
        # `{meeting_id}:{ordinal}` — one meeting's list is rewritten whole, so
        # the pair is stable and unique without a sequence.
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("meeting_id", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by", sa.String(length=512), nullable=False),
        sa.Column("confirmed_at", sa.String(length=64), nullable=False),
        # Append order within a meeting. A re-confirmation after a late
        # arrival is the one that describes the meeting as it was recorded, so
        # which came last has to survive the restart too.
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_consent_records_meeting_id",
        "consent_records",
        ["meeting_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_consent_records_meeting_id", table_name="consent_records")
    op.drop_table("consent_records")
