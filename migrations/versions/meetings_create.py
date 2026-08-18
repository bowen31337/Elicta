"""create meetings table

Revision ID: meetings
Revises: open_questions
Create Date: 2026-08-18

Records one row per session within an engagement (PRD FR-3.8): its purpose
and the target template sections it is meant to cover, when it is
scheduled, the audio capture mode (monolingual vs. code-switched) that
gates live WER expectations, and its lifecycle state. `engagement_id` is a
foreign key rather than a duplicated copy of engagement context, since
FR-3.7 requires the meeting to inherit that context automatically rather
than re-enter it.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "meetings"
down_revision = "open_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "target_sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "capture_mode",
            sa.String(length=16),
            nullable=False,
            server_default="monolingual",
        ),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="scheduled",
        ),
    )
    op.create_index(
        "ix_meetings_engagement_id",
        "meetings",
        ["engagement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_meetings_engagement_id", table_name="meetings")
    op.drop_table("meetings")
