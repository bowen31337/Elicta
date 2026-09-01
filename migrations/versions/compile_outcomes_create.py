"""create compile_outcomes table

Revision ID: compile_outcomes
Revises: compile_batches
Create Date: 2026-09-01

What one bank compile did, and how far it got.

`compile_runs` was a plain dict and `bank_compiles` a plain list, so a restart
erased both: the endpoint answered "no bank compile has run for this
engagement" about an engagement compiled minutes earlier, and the Preparation
screen showed no meter, no stage and no reason. Every failure the compile work
made visible went invisible again at the next launch — which, given how often
this app is rebuilt, is most of the time.

`finished_at` is null while a compile is in flight, and that is the whole of
how a compile the process died during is told from one that completed. The
task is gone and nothing will finish it, so on the next launch a row still
open is reported stopped, with what happened. Reported running it would be a
spinner nobody can stop; reported as never-run it would be a lie about work
that was done and billed.
"""

from alembic import op
import sqlalchemy as sa

revision = "compile_outcomes"
down_revision = "compile_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compile_outcomes",
        sa.Column("compile_id", sa.String(length=64), primary_key=True),
        sa.Column("engagement_id", sa.String(length=64), nullable=False),
        sa.Column("stages_completed", sa.JSON(), nullable=True),
        sa.Column("stopped_at", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        # Null while it is running. See the note above: this column is what
        # separates "still going" from "the process died holding it".
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("compile_outcomes")
