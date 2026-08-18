"""create replay_ratings table

Revision ID: replay_ratings
Revises: replay_runs
Create Date: 2026-08-18

Records a senior BA's verdict on one suggestion surfaced during a replay
run: useful, timely, and embarrassing (architecture section 9). Two BAs
rate the same suggestion independently, so a suggestion can have more than
one row; precision@surfaced (M1) and the embarrassment gate (M2) are
computed from this table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "replay_ratings"
down_revision = "replay_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_ratings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggestion_surfaced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=False),
        sa.Column("candidate", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rater", sa.String(length=128), nullable=False),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("timely", sa.Boolean(), nullable=False),
        sa.Column("embarrassing", sa.Boolean(), nullable=False),
        sa.Column(
            "rated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_replay_ratings_run_id",
        "replay_ratings",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_replay_ratings_run_id", table_name="replay_ratings")
    op.drop_table("replay_ratings")
