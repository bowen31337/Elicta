"""create debrief_outcomes table

Revision ID: debrief_outcomes
Revises: bmad_chains
Create Date: 2026-08-26

Why a debrief run stopped, which used to die with the process.

`bmad_chains` holds what a run produced. This holds what became of it, and
the two are not the same record: a pipeline that stopped at diarization
produces no chain at all, so the reason it stopped is the only thing there
is to tell the operator — and it was kept in a plain dict.

Found on a meeting with eight completed transcripts, no artifacts, and a
screen reading "No write-up has been produced for this meeting yet — one
runs on its own once the recording has been transcribed." The recording had
been transcribed. Something had run, and stopped, and nothing anywhere
remembered what.

The same classification error six other collections have already been moved
out of. Nothing rebuilds this: re-running the pipeline is minutes of model
calls, and would report what happens now rather than what happened then.
"""

from alembic import op
import sqlalchemy as sa

revision = "debrief_outcomes"
down_revision = "bmad_chains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debrief_outcomes",
        # One outcome per session, replaced when the write-up is asked for
        # again.
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        # Null when the run finished. Named rather than boolean because
        # "stopped while telling the voices apart" and "stopped while
        # drafting the documents" are different things to an operator.
        sa.Column("stopped_at", sa.String(length=64), nullable=True),
        # The stage's own error text, for whoever is debugging the pipeline.
        # The sentence the operator reads is composed in the panel, where the
        # reader is — a live run put a stage record's own words on screen
        # once, and they were addressed to somebody else.
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("stages_completed", sa.JSON(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("debrief_outcomes")
