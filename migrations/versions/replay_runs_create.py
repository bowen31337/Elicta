"""create replay_runs table

Revision ID: replay_runs
Revises:
Create Date: 2026-08-18

Records one row per replay-harness invocation: the input recording, the
pipeline commit hash, and the random seed, so a run's output can be
reproduced byte-for-byte (architecture section 9).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "replay_runs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("recording_uri", sa.Text(), nullable=False),
        sa.Column("pipeline_commit", sa.String(length=64), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("replay_runs")
