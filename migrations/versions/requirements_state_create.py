"""create requirements_state table

Revision ID: requirements_state
Revises: engagements
Create Date: 2026-08-18

Persists the engagement-scoped standing requirements state `state.py`'s
`merge_requirements_state_forward` upserts after every meeting's debrief
pipeline completes (PRD FR-8.9): the confirmed requirements, contradictions,
and decisions carried forward across meetings. There is exactly one row per
engagement — `engagement_id` is the primary key rather than a separate
surrogate id — so the next meeting in the engagement always reads the
latest merged state via a lookup on the engagement itself.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "requirements_state"
down_revision = "engagements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requirements_state",
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "confirmed_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "contradictions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("requirements_state")
