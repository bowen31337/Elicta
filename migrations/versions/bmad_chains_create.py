"""create bmad_chains table

Revision ID: bmad_chains
Revises: surfaced_nudges
Create Date: 2026-08-26

The debrief's output, which is the product's output.

`SessionBmadAnalystChain` describes itself as a "Durable record of one BMAD
analyst chain run" and was held in a plain dict, so a restart took it — and
with it the project brief, the decision log, the open questions and the
follow-up email, all four of which read that one record. The same
classification error five other collections were already moved out of:
"rebuilt on demand" turning out to mean "lost on restart". Nothing rebuilds
this one either. It is a model pipeline over a whole meeting's transcript.

Not the `artifacts` table, which holds one rendered artifact per row and has
nowhere to put `status`, `engine` or `error` — and those are the fields that
make a failed run visible rather than silent, which is the distinction the
record exists to keep. The artifact set travels as JSON beside them, the way
a transcript's segments already do.
"""

from alembic import op
import sqlalchemy as sa

revision = "bmad_chains"
down_revision = "surfaced_nudges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bmad_chains",
        # One run per session, replaced when it is run again.
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        # Null on a failed run. The classified utterances outlive it
        # elsewhere, so nothing is lost by the artifacts being absent — but a
        # row with no artifacts and no status would be indistinguishable from
        # a session nobody has debriefed.
        sa.Column("artifacts", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bmad_chains")
