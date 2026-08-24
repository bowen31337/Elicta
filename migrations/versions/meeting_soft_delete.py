"""Mark meetings deleted instead of erasing them.

`soft_delete_marks` gave engagements, reference documents and vocabulary terms
a `deleted_at`. Meetings were left out because nothing could delete one: the
meetings router served POST, PATCH and the engagement-scoped list, so the
Preparation screen's list of meetings was append-only and an operator who
created one by mistake had no way back.

Adding the removal means adding the column, and for the same reason the others
have it: a meeting is the row a consent record, a record-path transcript and an
audio-destruction event all hang off. Hiding it from a list an operator has to
read is a different act from erasing the evidence that the meeting took place,
and only the first one is on offer here.

Written out as a single `add_column` rather than a loop for the reason
`soft_delete_marks` documents: `test_migrations` reads this chain with an AST
parse — it is written for PostgreSQL and cannot be replayed against the SQLite
the suite runs on — so a column added through a variable is a column that guard
cannot see.

Revision ID: meeting_soft_delete
Revises: voiceprints_portable
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "meeting_soft_delete"
down_revision = "voiceprints_portable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "deleted_at")
