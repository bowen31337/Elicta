"""create engagements table

Revision ID: engagements
Revises: egress_log
Create Date: 2026-08-18

Records the standing, engagement-level context captured once and inherited
by every meeting in the engagement (PRD FR-3.1, FR-3.5): the client
background (name, sector), the engagement's purpose and scope boundary, the
target requirements template, and the language settings that scope live
detection and fix the artifact output language. Per-meeting setup then
reduces to confirming what is already here, rather than re-entering it.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "engagements"
down_revision = "egress_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("client_name", sa.String(length=256), nullable=False),
        sa.Column("sector", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("scope_boundary", sa.Text(), nullable=False),
        sa.Column("template_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_language", sa.String(length=16), nullable=False),
        sa.Column(
            "expected_languages",
            postgresql.ARRAY(sa.String(length=16)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_table("engagements")
