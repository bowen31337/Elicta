"""create operator_voiceprints table

Revision ID: operator_voiceprints
Revises: replay_ratings
Create Date: 2026-08-18

Stores the enrolled speaker embedding for an operator (PRD FR-1.5), used by
the mixed-stream fallback path to verify who is speaking when capture does
not deliver a per-participant stream (architecture section 3.3). One
enrolled embedding per operator; re-enrolment replaces the row rather than
adding another.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "operator_voiceprints"
down_revision = "replay_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_voiceprints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("sample_duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_operator_voiceprints_operator_id",
        "operator_voiceprints",
        ["operator_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_operator_voiceprints_operator_id", table_name="operator_voiceprints")
    op.drop_table("operator_voiceprints")
