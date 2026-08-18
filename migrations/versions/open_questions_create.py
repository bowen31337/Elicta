"""create open_questions table

Revision ID: open_questions
Revises: requirements_state
Create Date: 2026-08-18

Persists the ranked open-questions list the BMAD analyst chain raises for a
session (PRD FR-8.3): `OpenQuestion` in `debrief/pipeline/models.py` pairs
each question's text with an `impact_rank`, a provenance flag (PRD FR-8.8),
and its grounding citations (PRD FR-8.7). `impact_rank` is a plain column
rather than folded into the JSONB payload specifically so the list can be
ordered by impact on the build with an indexed query instead of sorting the
payload client-side.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "open_questions"
down_revision = "requirements_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "open_questions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("impact_rank", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(length=16), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_open_questions_session_id_impact_rank",
        "open_questions",
        ["session_id", "impact_rank"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_open_questions_session_id_impact_rank", table_name="open_questions"
    )
    op.drop_table("open_questions")
