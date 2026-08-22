"""Mark rows deleted instead of erasing them.

Engagements, reference documents and vocabulary terms gain a `deleted_at`.
Set, the row stops being loaded and disappears from every list; unset, nothing
changes. Nothing erases.

That is deliberate for this product: a removal stays reversible, an audit can
still see what was there, and the harder question — whether a real erasure
should also destroy recordings, consent records and debrief artifacts — stays
open instead of being answered by a `DELETE` nobody discussed.

Written out one table at a time rather than looped: `test_migrations` reads
this chain with an AST parse, because it is written for PostgreSQL and cannot
be replayed against SQLite, so a column added through a variable is a column
that guard cannot see.

Revision ID: soft_delete_marks
Revises: document_and_vocabulary_continuity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "soft_delete_marks"
down_revision = "document_and_vocabulary_continuity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engagements", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("reference_documents", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("vocabulary_terms", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("vocabulary_terms", "deleted_at")
    op.drop_column("reference_documents", "deleted_at")
    op.drop_column("engagements", "deleted_at")
