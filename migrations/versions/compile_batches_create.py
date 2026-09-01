"""create compile_batches table

Revision ID: compile_batches
Revises: requirements_state_rekey
Create Date: 2026-09-01

An analyst batch that was submitted and has not been collected yet.

A compile does its work in two visits: the Analyst pass goes to the provider
as a batch, `fetch_batch` returns nothing while it is still processing, and
`BankCollector` sweeps until it comes back. The sweep reads the in-flight
compiles, and those lived in a plain dict — so a restart inside that window
left nothing to sweep. The batch was paid for, the bank never updated, and no
screen mentioned it.

A batch may take hours, which makes a restart inside the window ordinary
rather than exceptional. That is what separates this from the other
collections moved out of "rebuilt on demand": here the thing lost is not a
record of work, it is work still owed.

Only what the collector needs to go back for it, and the row goes once the
batch has been collected. It describes an obligation, not a history.
"""

from alembic import op
import sqlalchemy as sa

revision = "compile_batches"
down_revision = "requirements_state_rekey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compile_batches",
        sa.Column("compile_id", sa.String(length=64), primary_key=True),
        sa.Column("engagement_id", sa.String(length=64), nullable=False),
        # The provider's own handle. Without it the batch cannot be asked
        # after, which is the whole of what this row is for.
        sa.Column("batch_job_id", sa.String(length=128), nullable=False),
        sa.Column("stages_completed", sa.JSON(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("compile_batches")
