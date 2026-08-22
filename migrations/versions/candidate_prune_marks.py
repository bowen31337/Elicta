"""Keep the operator's pruning of the question bank.

`BankCandidate` has carried a `pruned` flag since the review endpoints were
built, and the table it is stored in never had a column for it. The PATCH
answered 200, the screen redrew, and the flag lived in the service process and
nowhere else — so every restart handed back a bank with the whole review
undone.

Pruning is also promised to hold across meetings: a question rejected once is
never offered again. A flag that does not outlive the process cannot make that
promise, so this is the column that promise rests on.

`server_default` is set because the column is `NOT NULL` and rows already
exist: on PostgreSQL an added `NOT NULL` column with no default is refused
outright, and a bank compiled before this revision is exactly the case that
would hit it. Nothing pruned before this revision can be recovered — it was
never written down.

Revision ID: candidate_prune_marks
Revises: soft_delete_marks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "candidate_prune_marks"
down_revision = "soft_delete_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("pruned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("candidates", "pruned")
